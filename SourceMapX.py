#!/usr/bin/env python3
"""
    unwebpack_sourcemap.py
    by rarecoil (github.com/rarecoil/unwebpack-sourcemap)

    Reads Webpack source maps and extracts the disclosed
    uncompiled/commented source code for review. Can detect and
    attempt to read sourcemaps from Webpack bundles with the `-d`
    flag. Puts source into a directory structure similar to dev.
"""

import gevent
from gevent import monkey
monkey.patch_all()
import argparse
import json
import os
import re
import string
import sys
from urllib.parse import urlparse
from unicodedata import normalize

import requests
from bs4 import BeautifulSoup, SoupStrainer

from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

class SourceMapExtractor(object):
    """Primary SourceMapExtractor class. Feed this arguments."""

    _target = None
    _path_sanitiser = None

    def __init__(self, target,output):
        """Initialize the class."""
        self._output = output
        self._target = target
        self._path_sanitiser = PathSanitiser(output)

    def run(self):
        self._parse_sourcemap(self._target)

    def _parse_sourcemap(self, target, is_str=False):
        map_data = ""
        if is_str is False:
            if os.path.isfile(target):
                with open(target, 'r', encoding='utf-8', errors='ignore') as f:
                    map_data = f.read()
        else:
            map_data = target

        # with the sourcemap data, pull directory structures
        try:
            map_object = json.loads(map_data)
        except json.JSONDecodeError:
            print("ERROR: Failed to parse sourcemap %s. Are you sure this is a sourcemap?" % target)
            return False
        except:
            return False

        # we need `sourcesContent` and `sources`.
        # do a basic validation check to make sure these exist and agree.
        if 'sources' not in map_object or 'sourcesContent' not in map_object:
            print("ERROR: Sourcemap does not contain sources and/or sourcesContent, cannot extract.")
            return False

        if len(map_object['sources']) != len(map_object['sourcesContent']):
            print("WARNING: sources != sourcesContent, filenames may not match content")

        idx = 0
        for source in map_object['sources']:
            if idx < len(map_object['sourcesContent']):
                path = source
                content = map_object['sourcesContent'][idx]
                idx += 1

                # remove webpack:// from paths
                # and do some checks on it
                write_path = self._get_sanitised_file_path(source)
                if write_path is not None:
                    try:
                        os.makedirs(os.path.dirname(write_path), mode=0o755, exist_ok=True)
                        with open(write_path, 'w', encoding='utf-8', errors='ignore') as f:
                            print("Writing %s..." % os.path.basename(write_path))
                            f.write(content)
                            f.write("\n")
                    except:
                        pass
            else:
                break

    def _get_sanitised_file_path(self, sourcePath):
        """Sanitise webpack paths for separators/relative paths"""
        sourcePath = sourcePath.replace("webpack:///", "")
        exts = sourcePath.split(" ")

        if exts[0] == "external":
            print("WARNING: Found external sourcemap %s, not currently supported. Skipping" % exts[1])
            return None

        path, filename = os.path.split(sourcePath)
        if path[:2] == './':
            path = path[2:]
        if path[:3] == '../':
            path = 'parent_dir/' + path[3:]
        if path[:1] == '.':
            path = ""

        filepath = self._path_sanitiser.make_valid_file_path(path, filename)
        return filepath

    def _get_remote_data(self, uri):
        """Get remote data via http."""
        try:
            result = requests.get(uri,verify=False,timeout=30)
        
            if result.status_code == 200:
                return result.text
            else:
                print("WARNING: Got status code %d for URI %s" % (result.status_code, uri))
                return False
        except:
            return False

class PathSanitiser(object):
    """https://stackoverflow.com/questions/13939120/sanitizing-a-file-path-in-python"""

    root_path = ""

    def __init__(self, root_path):
        self.root_path = root_path

    def ensure_directory_exists(self, path_directory):
        if not os.path.exists(path_directory):
            os.makedirs(path_directory)

    def os_path_separators(self):
        seps = []
        for sep in os.path.sep, os.path.altsep:
            if sep:
                seps.append(sep)
        return seps

    def sanitise_filesystem_name(self, potential_file_path_name):
        # Sort out unicode characters
        valid_filename = normalize('NFKD', potential_file_path_name).encode('ascii', 'ignore').decode('ascii')
        # Replace path separators with underscores
        for sep in self.os_path_separators():
            valid_filename = valid_filename.replace(sep, '_')
        # Ensure only valid characters
        valid_chars = "-_.() {0}{1}".format(string.ascii_letters, string.digits)
        valid_filename = "".join(ch for ch in valid_filename if ch in valid_chars)
        # Ensure at least one letter or number to ignore names such as '..'
        valid_chars = "{0}{1}".format(string.ascii_letters, string.digits)
        test_filename = "".join(ch for ch in potential_file_path_name if ch in valid_chars)
        return valid_filename

    def get_root_path(self):
        # Replace with your own root file path, e.g. '/place/to/save/files/'
        filepath = self.root_path
        filepath = os.path.abspath(filepath)
        # ensure trailing path separator (/)
        if not any(filepath[-1] == sep for sep in self.os_path_separators()):
            filepath = '{0}{1}'.format(filepath, os.path.sep)
        self.ensure_directory_exists(filepath)
        return filepath

    def path_split_into_list(self, path):
        # Gets all parts of the path as a list, excluding path separators
        parts = []
        while True:
            newpath, tail = os.path.split(path)
            if newpath == path:
                assert not tail
                if path and path not in self.os_path_separators():
                    parts.append(path)
                break
            if tail and tail not in self.os_path_separators():
                parts.append(tail)
            path = newpath
        parts.reverse()
        return parts

    def sanitise_filesystem_path(self, potential_file_path):
        # Splits up a path and sanitises the name of each part separately
        path_parts_list = self.path_split_into_list(potential_file_path)
        sanitised_path = ''
        for path_component in path_parts_list:
            sanitised_path = '{0}{1}{2}'.format(sanitised_path,
                self.sanitise_filesystem_name(path_component),
                os.path.sep)
        return sanitised_path

    def check_if_path_is_under(self, parent_path, child_path):
        # Using the function to split paths into lists of component parts, check that one path is underneath another
        child_parts = self.path_split_into_list(child_path)
        parent_parts = self.path_split_into_list(parent_path)
        if len(parent_parts) > len(child_parts):
            return False
        return all(part1==part2 for part1, part2 in zip(child_parts, parent_parts))

    def make_valid_file_path(self, path=None, filename=None):
        root_path = self.get_root_path()
        if path:
            sanitised_path = self.sanitise_filesystem_path(path)
            if filename:
                sanitised_filename = self.sanitise_filesystem_name(filename)
                complete_path = os.path.join(root_path, sanitised_path, sanitised_filename)
            else:
                complete_path = os.path.join(root_path, sanitised_path)
        else:
            if filename:
                sanitised_filename = self.sanitise_filesystem_name(filename)
                complete_path = os.path.join(root_path, sanitised_filename)
            else:
                complete_path = complete_path
        complete_path = os.path.abspath(complete_path)
        if self.check_if_path_is_under(root_path, complete_path):
            return complete_path
        else:
            return None

class SourceMapExtractorError(Exception):
    pass

def readfile(pfile):
    fp = open(pfile,"r")
    content = fp.read()
    fp.close()
    return content

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="A tool to extract code from Webpack sourcemaps. Turns black boxes into gray ones.")
    parser.add_argument("-o", "--output", default="./output/",
        help="Make the output directory if it doesn't exist.")
    parser.add_argument("sdir", help="The target directory containing .map files.")

    args = parser.parse_args()
    targets = []

    # 检查目标目录是否存在
    if not os.path.isdir(args.sdir):
        print(f"Error: Directory '{args.sdir}' does not exist.")
        sys.exit(1)

    # 只查找根目录下的.map文件（不递归子目录）
    for file in os.listdir(args.sdir):
        if file.endswith(".map"):
            map_file_path = os.path.join(args.sdir, file)
            targets.append(map_file_path)

    # 如果没有找到.map文件
    if not targets:
        print(f"No .map files found in directory: {args.sdir}")
        sys.exit(0)

    print(f"Found {len(targets)} .map files to process:")

    # 处理每个.map文件
    for target in targets:
        extractor = SourceMapExtractor(target, args.output)
        extractor.run()