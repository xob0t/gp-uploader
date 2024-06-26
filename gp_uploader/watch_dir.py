import logging
import os
from pathlib import Path
import subprocess
import time
import argparse
from rich.logging import RichHandler
import uiautomator2 as u2

class Watcher:
    def __init__(self,target_path, serial = "", host_keep = False, log_uploads = False, log_level = ""):
        self.logger = self._new_logger(log_level)
        self.s = serial
        self.host_keep = host_keep
        self.log_uploads = log_uploads
        self.device = None
        self.uploaded = self._get_uploaded()
        self.device_media_path = Path("/sdcard/DCIM")
        self.target_path = Path(target_path)

    def _new_logger(self, log_level):
        logging.basicConfig(
            level=log_level,
            format="%(message)s",
            datefmt="%H:%M:%S",
            handlers=[RichHandler(rich_tracebacks=True)],
        )
        return logging.getLogger("rich")

    def _wait_for_device(self):
        self.logger.info("Waiting for device")
        while True:
            try:
                d = u2.connect(self.s)
                self.logger.debug(d.info)
                self.logger.info("Device found")
                return d
            except:
                time.sleep(0.5)

    def upload_files(self):
        self.device = self._wait_for_device()
        files = os.listdir(self.target_path)
        self.uploaded = self._get_uploaded()
        if not files:
            time_to_sleep = 30
            self.logger.info(f"Empty dir, checking again in {time_to_sleep}s")
            time.sleep(time_to_sleep)
            return
        new_files = [file_name for file_name in files if file_name not in self.uploaded]
        if not new_files:
            time_to_sleep = 30
            self.logger.info(f"No new files to upload, checking again in {time_to_sleep}s")
            time.sleep(time_to_sleep)
            return
        for file in new_files:
            host_file_path = Path.joinpath(self.target_path, file).as_posix()
            device_file_path = Path.joinpath(self.device_media_path, file).as_posix()
            try:
                self._upload(host_file_path, device_file_path)
                self._save_as_uploaded(file)
            except Exception as e:
                self.logger.critical("upload error")

    def watch(self):
        while True:
            try:
                self.upload_files()
            except Exception as e:
                self.logger.critical(e)
                time.sleep(30)


    def _upload(self, host_file_path, device_file_path):
        host_file_size = Path(host_file_path).stat().st_size
        device_file_size = self._get_file_size_on_device(device_file_path)
        if host_file_size != device_file_size:
            device_file_path = self._push_to_device(host_file_path, device_file_path)
        self._start_upload(device_file_path)
        while True:
            upload_text_check = self.device(text="Uploading Photos", className="android.widget.TextView")
            if upload_text_check.exists:
                self.logger.debug("Upload in progress")
                time.sleep(1)
                continue
            elif self.device.toast.get_message(1, 60) == "Upload complete":
                self.device.toast.reset()
                self.logger.info("Upload complete")
                if not self.host_keep:
                    file_name = Path(device_file_path).name
                    self.logger.info(f"Deleting {file_name} from host")
                    os.remove(host_file_path)
                self._delete_from_device(device_file_path)
                break
            elif (
                self.device.toast.get_message(1, 60) == "Error, could not upload media"
                or not upload_text_check.exists):
                self.device.toast.reset()
                self.logger.info("Error, could not upload media")
                break

    def _save_as_uploaded(self, filename):
        # Open the file in append mode
        with open("uploaded.txt", "a", encoding="UTF-8") as file:
            file.write(f"{filename}\n")

    def _get_uploaded(self):
        if not Path("uploaded.txt").exists():
            return []
        with open("uploaded.txt", "r", encoding="UTF-8") as file:
            lines =  file.readlines()
        return [line.strip() for line in lines]


    def _get_file_size_on_device(self, device_file_path):
        file_name = Path(device_file_path).name
        self.logger.debug(f"Checking {file_name} file size on device")
        output = self.device.shell(f'stat -c %s "{device_file_path}"', timeout=60).output
        try:
            size = int(output)
        except:
            size = 0
        return size
    
    def _push_to_device(self, host_file_path, device_file_path):
        self.logger.info(f"Pushing {host_file_path} to device")
        cmd = ["adb", "push", host_file_path, device_file_path]
        cmd = cmd[:1] + ["-s", self.s] + cmd[1:] if self.s else None
        subprocess.run(cmd, check=True)
        return device_file_path
    
    def _delete_from_device(self, device_file_path):
        file_name = Path(device_file_path).name
        self.logger.info(f"Deleting {file_name} from device")
        exit_code = self.device.shell(f'rm "{device_file_path}"', timeout=60).exit_code
        assert exit_code == 0

    def _get_file_size_on_device(self, device_file_path):
        file_name = Path(device_file_path).name
        self.logger.debug(f"Checking {file_name} file size on device")
        output = self.device.shell(f'stat -c %s "{device_file_path}"', timeout=60).output
        try:
            size = int(output)
        except:
            size  = 0
        return size

    def _start_upload(self, device_file_path):
        file_name = Path(device_file_path).name
        self.logger.info(f"Starting upload {file_name}")
        uri = f"file://{device_file_path}"
        exit_code = self.device.shell(
            f'am start -a android.intent.action.SEND -t application/octet-stream -n com.google.android.apps.photos/.upload.intent.UploadContentActivity --eu android.intent.extra.STREAM "{uri}"',
            timeout=60,
        ).exit_code
        assert exit_code == 0
        upload_button = '//*[@resource-id="com.google.android.apps.photos:id/upload_button" and @clickable="true" and @enabled="true"]'
        self.device.xpath(upload_button).click(timeout=60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dir", type=str, help="Directory path to watch")
    parser.add_argument("-s", "--serial", type=str, help="Serial of the device to connect to")
    parser.add_argument("-k", "--host-keep", type=bool, help="Do not delete host files on successful upload")
    parser.add_argument("-u", "--log-uploads", type=bool, help="Keep log of successful uploads in uploaded.txt")
    parser.add_argument("-l", "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default="INFO", help="Log level")
    args = parser.parse_args()

    u = Watcher(args.dir, args.serial, args.host_keep, args.log_uploads, args.log_level)
    u.watch()


if __name__ == "__main__":
    main()
