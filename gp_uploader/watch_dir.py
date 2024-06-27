import logging
import os
from pathlib import Path
import subprocess
import time
import argparse
from io import BytesIO
from lxml import etree
from rich.logging import RichHandler


class Adb_utils:
    def __init__(self, serial=""):
        self.device = ["adb", "-s", serial] if serial else ["adb"]

    def _get_ui_hierarchy_dump(self):
        cmd = self.device + ["exec-out", "uiautomator dump /dev/tty"]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        # The output will contain some additional lines, so we need to extract the XML part
        xml_end = result.stdout.find("UI hierchary dumped to")
        xml_content = result.stdout[:xml_end]
        if not xml_content:
            raise Exception("uiautomator dump is empty")
        return xml_content

    def get_element_coordinates_by_xpath(self, xpath):
        xml_content = self._get_ui_hierarchy_dump()
        # Parse the XML content
        xml_content_bytes = xml_content.encode("utf-8")
        # Parse the XML content
        tree = etree.parse(BytesIO(xml_content_bytes))
        root = tree.getroot()

        # Find the element by XPath
        element = root.xpath(xpath)
        if element:
            element = element[0]  # Take the first match if there are multiple
            bounds = element.attrib["bounds"]
            # Extract the coordinates
            bounds = bounds.replace("[", "").replace("]", ",").split(",")
            x = (int(bounds[0]) + int(bounds[2])) // 2
            y = (int(bounds[1]) + int(bounds[3])) // 2
            return x, y
        else:
            return None

    def click_coordinates(self, coordinates):
        if coordinates:
            x, y = coordinates
            subprocess.run(["adb", "shell", "input", "tap", str(x), str(y)])
        else:
            raise Exception(f"Element not found for coordinates: {coordinates}")

    def wait_for_element_by_xpath(self, xpath, timeout=60):
        start_time = time.time()
        while time.time() - start_time < timeout:
            element = self.get_element_coordinates_by_xpath(xpath)
            if element:
                return element
            time.sleep(1)  # Check every 1 second
        return None


class Watcher:
    def __init__(self, target_path, serial="", host_keep=False, log_uploads=False, log_level=""):
        self.logger = self._new_logger(log_level)
        self.device = ["adb", "-s", serial] if serial else ["adb"]
        self.host_keep = host_keep
        self.log_uploads = log_uploads
        self.uploaded = self._get_uploaded()
        self.device_media_path = Path("/sdcard/DCIM")
        self.target_path = Path(target_path)
        self.upload_status = None  # used for toast monitoring
        self.adb_utils = Adb_utils(serial)
        self.upload_btn_coords = None

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
                # testing adb connection
                cmd = self.device + ["shell", "getprop", "ro.product.model"]
                device_model = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True).stdout.strip()
                self.logger.info(f"Device found: {device_model}")
                return
            except Exception as e:
                self.logger.debug(e)
                time.sleep(0.5)

    def _start_upload(self):
        command = self.device + ["shell", "uiautomator events"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        try:
            self.adb_utils.click_coordinates(self.upload_btn_coords)
            self.logger.info("waiting for status toast")
            while True:
                # Read a line from the events log
                line = process.stdout.readline()
                # Check if the target text is in the line
                if "Upload complete" in line:
                    return True
                elif "Error, could not upload media" in line:
                    return False
        except KeyboardInterrupt:
            pass
        finally:
            # Clean up: terminate the log process
            process.terminate()
            process.wait()

    def upload_files(self):
        self._wait_for_device()
        # get files
        files = [f for f in Path(self.target_path).iterdir() if f.is_file()]
        self.uploaded = self._get_uploaded()
        if not files:
            time_to_sleep = 30
            self.logger.info(f"Empty dir, checking again in {time_to_sleep}s")
            time.sleep(time_to_sleep)
            return
        new_files = [file for file in files if file.name not in self.uploaded]
        if not new_files:
            time_to_sleep = 30
            self.logger.info(f"No new files to upload, checking again in {time_to_sleep}s")
            time.sleep(time_to_sleep)
            return
        for file in new_files:
            host_file_path = file
            device_file_path = Path.joinpath(self.device_media_path, file.name)
            try:
                self._upload(host_file_path, device_file_path)
            except Exception as e:
                self.logger.critical(e)

    def watch(self):
        while True:
            try:
                self.upload_files()
            except Exception as e:
                self.logger.critical(e)
                time.sleep(30)

    def _upload(self, host_file_path, device_file_path):
        host_file_size = host_file_path.stat().st_size
        device_file_size = self._get_file_size_on_device(device_file_path)
        if host_file_size != device_file_size:
            device_file_path = self._push_to_device(host_file_path, device_file_path)
        self._send_intent(device_file_path)
        upload_button_xpath = '//*[@resource-id="com.google.android.apps.photos:id/upload_button" and @clickable="true" and @enabled="true"]'
        self.adb_utils.wait_for_element_by_xpath(upload_button_xpath)
        if not self.upload_btn_coords:
            self.upload_btn_coords = self.adb_utils.get_element_coordinates_by_xpath(upload_button_xpath)
        upload_status = self._start_upload()
        if upload_status is True:
            self.logger.info("Upload complete")
            self._save_as_uploaded(device_file_path.name)
            if not self.host_keep:
                self.logger.info(f"{device_file_path.name} deleting from host")
                os.remove(host_file_path)
            self._delete_from_device(device_file_path)
        else:
            self.logger.info("Error, could not upload media")

    def _save_as_uploaded(self, filename):
        with open("uploaded.txt", "a", encoding="UTF-8") as file:
            file.write(f"{filename}\n")

    def _get_uploaded(self):
        if not Path("uploaded.txt").exists():
            return []
        with open("uploaded.txt", "r", encoding="UTF-8") as file:
            lines = file.readlines()
        return [line.strip() for line in lines]

    def _get_file_size_on_device(self, device_file_path):
        self.logger.debug(f"{device_file_path.name} checking file size on device")
        output = subprocess.run(self.device + ["shell", f'stat -c %s "{device_file_path}"'], capture_output=True, text=True, check=False)
        try:
            size = int(output.stdout.strip())
        except:
            size = 0
        return size

    def _push_to_device(self, host_file_path, device_file_path):
        self.logger.info(f"{device_file_path.name} Pushing to device")
        cmd = self.device + ["push", host_file_path.as_posix(), device_file_path.as_posix()]
        subprocess.run(cmd, check=True)
        return device_file_path

    def _delete_from_device(self, device_file_path):
        self.logger.info(f"{device_file_path.name} deleting from device")
        subprocess.run(self.device + ["shell", f'rm "{device_file_path.as_posix()}"'], check=True)

    def _send_intent(self, device_file_path):
        self.logger.info(f"{device_file_path.name} starting upload")
        uri = "file://" + device_file_path.as_posix()
        process = subprocess.run(
            self.device + ["shell", "am", "start", "-a", "android.intent.action.SEND", "-t", "application/octet-stream",
                           "-n", "com.google.android.apps.photos/.upload.intent.UploadContentActivity",
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
    parser.add_argument("-k", "--host-keep", action="store_true", help="Do not delete host files on successful upload")
    parser.add_argument("-u", "--log-uploads", action="store_true", help="Keep log of successful uploads in uploaded.txt")
    parser.add_argument("-l", "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], default="INFO", help="Log level")
    args = parser.parse_args()

    u = Watcher(args.dir, args.serial, args.host_keep, args.log_uploads, args.log_level)
    u.watch()


if __name__ == "__main__":
    main()
