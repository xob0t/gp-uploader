import logging
import os
from pathlib import Path
import subprocess
import time
import argparse
from urllib.parse import quote
import sqlite3
from rich.logging import RichHandler


class Watcher:
    def __init__(self, target_path, serial="", timeout=None, gpdb_path="", host_delete=False, no_log=False, log_level=""):
        self.logger = self._new_logger(log_level)
        self.device = ["adb", "-s", serial] if serial else ["adb"]
        self.timeout = timeout
        self.gpdb_path = gpdb_path
        self.host_delete = host_delete
        self.no_log = no_log
        self.uploaded = self._get_uploaded()
        self.device_media_path = Path("/sdcard/DCIM")
        self.target_path = Path(target_path)
        self.current_upload_filename = ""
        self.timeout = 3000

    def _new_logger(self, log_level):
        logging.basicConfig(
            level=log_level,
            format="%(message)s",
            datefmt="%H:%M:%S",
            handlers=[RichHandler(rich_tracebacks=True)],
        )
        return logging.getLogger("rich")

    def _wait_for_device(self):
        self.logger.info("waiting for device")
        while True:
            try:
                # testing adb connection
                cmd = self.device + ["shell", "getprop", "ro.product.model"]
                device_model = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True).stdout.strip()
                self.logger.info(f"device found: {device_model}")
                return
            except Exception as e:
                self.logger.debug(e)
                time.sleep(0.5)

    def _wait_for_status(self):
        # logact clear may be inconsistent, so we clear it before and after upload
        self._clear_logcat()
        time.sleep(1)
        command = self.device + ["shell", "logcat"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        try:
            self.logger.info("waiting for status log")

            start_time = time.time()
            while True:
                # Read a line from the events log
                line = process.stdout.readline()
                # Check if the target text is in the line
                if "RevancedPhotos: uploadComplete" in line:
                    self._clear_logcat()
                    return True
                elif "RevancedPhotos: uploadError" in line:
                    self._clear_logcat()
                    return False
                if self.timeout and (time.time() - start_time > self.timeout):
                    self.logger.warning(f"{self.current_upload_filename} upload timeout reached")
                    break
        except KeyboardInterrupt:
            pass
        finally:
            # Clean up: terminate the log process
            process.terminate()
            process.wait()

    def watch(self):
        while True:
            try:
                self._upload_files()
                time.sleep(30)
            except Exception as e:
                self.logger.critical(e)
                time.sleep(30)

    def _upload_files(self):
        self._wait_for_device()
        # get files
        files = [f for f in Path(self.target_path).rglob("*") if f.is_file()]
        # gp does not like dotfiles sent via adb intents for some reason
        files = [f for f in files if not f.name.startswith(".")]
        self.uploaded = self._get_uploaded()
        if self.gpdb_path:
            self.uploaded.extend(self._get_remote_media_list())
        if not files:
            time_to_sleep = 30
            self.logger.info(f"empty dir, checking again in {time_to_sleep}s")
            time.sleep(time_to_sleep)
            return
        new_files = [file for file in files if file.name not in self.uploaded]
        if not new_files:
            time_to_sleep = 30
            self.logger.info(f"no new files to upload, checking again in {time_to_sleep}s")
            time.sleep(time_to_sleep)
            return
        for file in new_files:
            self._stop_photos()
            self.current_upload_filename = file.name
            host_file_path = file
            device_file_path = Path.joinpath(self.device_media_path, self.current_upload_filename)
            self._upload(host_file_path, device_file_path)

    def _upload(self, host_file_path, device_file_path):
        self._stop_photos()
        host_file_size = host_file_path.stat().st_size
        device_file_size = self._get_file_size_on_device(device_file_path)
        if host_file_size != device_file_size:
            device_file_path = self._push_to_device(host_file_path, device_file_path)
        self._send_intent(device_file_path)
        upload_status = self._wait_for_status()
        if upload_status is True:
            self.logger.info(f"{self.current_upload_filename} upload complete")
            if not self.no_log:
                self._save_as_uploaded(self.current_upload_filename)
            if self.host_delete:
                self.logger.info(f"{self.current_upload_filename} deleting from host")
                os.remove(host_file_path)
            self._delete_from_device(device_file_path)
        else:
            raise Exception(f"{self.current_upload_filename} upload error")

    def _save_as_uploaded(self, filename):
        with open("uploaded.txt", "a", encoding="UTF-8") as file:
            file.write(f"{filename}\n")

    def _get_uploaded(self):
        if not Path("uploaded.txt").exists():
            return []
        with open("uploaded.txt", "r", encoding="UTF-8") as file:
            lines = file.readlines()
        return [line.strip() for line in lines]

    def _stop_photos(self):
        self.logger.debug("killing Photos app")
        cmd = self.device + ["shell", "am", "force-stop", "app.revanced.android.photos"]
        subprocess.run(cmd, check=True)

    def _clear_logcat(self):
        self.logger.debug("logcat clear")
        cmd = self.device + ["logcat", "-c"]
        subprocess.run(cmd, check=True)

    def _get_file_size_on_device(self, device_file_path):
        self.logger.debug(f"{self.current_upload_filename} checking file size on device")
        output = subprocess.run(self.device + ["shell", f'stat -c %s "{device_file_path}"'], capture_output=True, text=True, check=False)
        try:
            size = int(output.stdout.strip())
        except:
            size = 0
        return size

    def _get_remote_media_list(self):
        self.logger.info("reading gphotos0.db")
        # Connect to the SQLite database
        conn = sqlite3.connect(self.gpdb_path)
        cursor = conn.cursor()

        cursor.execute("SELECT filename FROM remote_media")

        filenames = [row[0] for row in cursor.fetchall()]

        # Close the connection
        conn.close()

        return filenames

    def _push_to_device(self, host_file_path, device_file_path):
        self.logger.info(f"{self.current_upload_filename} pushing to device")
        cmd = self.device + ["push", host_file_path.as_posix(), device_file_path.as_posix()]
        subprocess.run(cmd, check=True)
        return device_file_path

    def _delete_from_device(self, device_file_path):
        self.logger.info(f"{self.current_upload_filename} deleting from device")
        subprocess.run(self.device + ["shell", f'rm "{device_file_path.as_posix()}"'], check=True)

    def _send_intent(self, device_file_path):
        self.logger.info(f"{self.current_upload_filename} starting upload")
        uri = "file://" + quote(device_file_path.as_posix())
        process = subprocess.run(
            self.device + ["shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "application/octet-stream",
                           "-n", "app.revanced.android.photos/com.google.android.apps.photos.upload.intent.UploadContentActivity",
                           "--eu", "android.intent.extra.STREAM", uri],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        self.logger.debug(process.stdout) if process.stdout else None
        self.logger.debug(process.stderr) if process.stderr else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dir", type=str, help="Directory path to watch")
    parser.add_argument("-s", "--serial", type=str, help="Serial of the device to connect to")
    parser.add_argument("-t", "--timeout", type=int, help="Upload timeout, seconds")
    parser.add_argument("-g", "--gpdb-path", type=str, help="gphotos0.db path, used for filtering out already uploaded files")
    parser.add_argument("-d", "--host-delete", action="store_true", help="Delete host files on successful upload")
    parser.add_argument("-n", "--no-log", action="store_true", help="Do not keep log of successful uploads in uploaded.txt")
    parser.add_argument("-l", "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default="INFO", help="Log level")
    args = parser.parse_args()

    u = Watcher(args.dir, args.serial, args.timeout, args.gpdb_path, args.host_delete, args.no_log, args.log_level)
    u.watch()


if __name__ == "__main__":
    main()
