"""Verify that a built executable requests administrator consent in Windows."""
import sys
from xml.etree import ElementTree


def check_manifest(xml):
    root = ElementTree.fromstring(xml)
    levels = [node for node in root.iter() if node.tag.rsplit('}', 1)[-1] == 'requestedExecutionLevel']
    if len(levels) != 1 or levels[0].get('level') != 'requireAdministrator' or levels[0].get('uiAccess') != 'false':
        raise ValueError('助手 EXE 未正确声明管理员启动权限')


def main():
    from PyInstaller.utils.win32.winmanifest import read_manifest_from_executable
    for filename in sys.argv[1:]:
        check_manifest(read_manifest_from_executable(filename))
        print(f'Administrator manifest verified: {filename}')
    if len(sys.argv) < 2:
        raise SystemExit('Please provide an executable path')


if __name__ == '__main__':
    main()
