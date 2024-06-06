from setuptools import find_packages, setup

setup(
    name='gp-uploader',
    version='0.0.1',
    description='Script to monitor a directory and upload any new files to google photo using adb connected android device',
    author='xob0t',
    url='https://github.com/xob0t/gp-uploader',
    packages=find_packages(),
    install_requires=[
        'rich',
        'uiautomator2==2.16.26',
    ],
    entry_points={
        'console_scripts': ['gp-uploader = gp_uploader.watch_dir:main']
    },
)