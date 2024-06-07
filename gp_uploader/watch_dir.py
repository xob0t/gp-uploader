import logging
import os
from pathlib import Path
import subprocess
import time
import argparse
from rich.logging import RichHandler
import uiautomator2 as u2


class Watcher:
    def __init__(self,target_path, serial = "", log_level = ""):
        self.logger = None
        self.log_level = log_level
        self.s = serial
        self.device = None
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

    def watch(self):
        self.logger = self._new_logger(self.log_level)
        self.device = self._wait_for_device()
        while True:
            files = os.listdir(self.target_path)
            if not files:
                time_to_sleep = 30
                self.logger.info(f"No files to upload, checking again in {time_to_sleep}s")
                time.sleep(time_to_sleep)
                continue
            self.logger.info(f"{len(files)} left to upload")
            for file in files:
                host_file_path = Path.joinpath(self.target_path, file).as_posix()
                device_file_path = self._push_to_device(host_file_path, file)
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
                        self.logger.info(f"Deleting {file} from host")
                        os.remove(host_file_path)
                        self._delete_from_device(device_file_path, file)
                        break
                    elif (
                        self.device.toast.get_message(1, 60) == "Error, could not upload media"
                        or not upload_text_check.exists):
                        self.device.toast.reset()
                        self.logger.info("Error, could not upload media")
                        break

    # def _push_to_device(self, host_file_path, file_name):
    #     self.logger.info(f"Pushing {host_file_path} to device")
    #     device_file_path = Path.joinpath(self.device_media_path, file_name).as_posix()
    #     self.device.push(host_file_path,device_file_path, show_progress = True)
    #     return device_file_path
    
    def _push_to_device(self, host_file_path, file_name):
        self.logger.info(f"Pushing {host_file_path} to device")
        device_file_path = Path.joinpath(self.device_media_path, file_name).as_posix()
        exit_code = None
        if self.s:
            exit_code = subprocess.run(["adb", "-s", self.s,  "push", host_file_path, device_file_path]).returncode
        else:
            exit_code = subprocess.run(["adb", "push", host_file_path, device_file_path]).returncode
        # self.device.push(host_file_path,device_file_path, show_progress = True)
        assert exit_code == 0
        return device_file_path
    
    def _delete_from_device(self, device_file_path, file_name):
        self.logger.info(f"Deleting {file_name} from device")
        exit_code = self.device.shell(f'rm "{device_file_path}"', timeout=60).exit_code
        assert exit_code == 0

    def _start_upload(self, device_file_path):
        self.logger.info(f"Uploading {device_file_path}")
        file = f"file://{device_file_path}"
        exit_code = self.device.shell(
            f'am start -a android.intent.action.SEND -t application/octet-stream -n com.google.android.apps.photos/.upload.intent.UploadContentActivity --eu android.intent.extra.STREAM "{file}"',
            timeout=60,
        ).exit_code
        assert exit_code == 0
        upload_button = '//*[@resource-id="com.google.android.apps.photos:id/upload_button" and @clickable="true" and @enabled="true"]'
        self.device.xpath(upload_button).click(timeout=60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dir", type=str, help="Directory path to watch")
    parser.add_argument("-s", "--serial", type=str, help="Serial of the device to connect to")
    parser.add_argument("-l", "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default="INFO", help="Log level")
    args = parser.parse_args()

    u = Watcher(args.dir, args.serial, args.log_level)
    u.watch()


if __name__ == "__main__":
    main()
