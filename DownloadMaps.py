import json
import os
import re
import requests
import argparse
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def parse_arguments():
    parser = argparse.ArgumentParser(description='下载网页加载的所有JS文件及其SourceMap')
    parser.add_argument('-o', '--output', help='指定输出目录', default='downloaded_js')
    return parser.parse_args()

def load_urls_from_file(filename="urls.txt"):
    urls = []
    try:
        with open(filename, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
        return urls
    except Exception as e:
        print(f"Error loading URLs from file: {str(e)}")
        return []

def download_file(url, save_path):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        with open(save_path, "wb") as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"Failed to download {url}: {str(e)}")
        return False

def extract_sourcemap_url(js_content):
    """从JS内容中提取sourceMappingURL"""
    pattern = r"//# sourceMappingURL=(.*\.map)"
    match = re.search(pattern, js_content.decode('utf-8', errors='ignore'))
    return match.group(1) if match else None

def process_js_file(js_url, download_dir):
    """处理单个JS文件"""
    js_filename = os.path.basename(js_url)
    js_path = os.path.join(download_dir, js_filename)
    
    # 下载JS文件
    if not download_file(js_url, js_path):
        return False
    
    print(f"Downloaded: {js_filename}")
    
    # 检查JS文件内容
    try:
        with open(js_path, "rb") as f:
            js_content = f.read()
        
        sourcemap_name = extract_sourcemap_url(js_content)
        if sourcemap_name:
            # 处理相对路径的sourceMappingURL
            if not sourcemap_name.startswith(('http://', 'https://')):
                base_url = os.path.dirname(js_url)
                sourcemap_url = f"{base_url}/{sourcemap_name}"
            else:
                sourcemap_url = sourcemap_name
            
            # 下载SourceMap文件
            map_filename = f"{js_filename}.map" if not sourcemap_name.endswith('.map') else sourcemap_name
            map_path = os.path.join(download_dir, os.path.basename(map_filename))
            
            if download_file(sourcemap_url, map_path):
                print(f"Downloaded SourceMap: {os.path.basename(map_path)}")
            else:
                print(f"Failed to download SourceMap: {sourcemap_url}")
        else:
            print(f"No SourceMap found in: {js_filename}")
    except Exception as e:
        print(f"Error processing {js_filename}: {str(e)}")

def process_url(driver, url, download_dir):
    print(f"\nProcessing URL: {url}")
    driver.get(url)
    
    logs = driver.get_log("performance")
    js_urls = set()

    for log in logs:
        try:
            log_data = json.loads(log["message"])
            if log_data.get("message", {}).get("method") == "Network.requestWillBeSent":
                request_url = log_data["message"]["params"]["request"].get("url", "")
                if request_url.endswith(".js"):
                    js_urls.add(request_url)
        except Exception as e:
            print(f"Error parsing log: {str(e)}")

    for js_url in js_urls:
        process_js_file(js_url, download_dir)

def main():
    args = parse_arguments()
    os.makedirs(args.output, exist_ok=True)
    print(f"Output directory: {os.path.abspath(args.output)}")

    urls = load_urls_from_file()
    if not urls:
        print("No valid URLs found in urls.txt")
        return

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    try:
        for url in urls:
            process_url(driver, url, args.output)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()