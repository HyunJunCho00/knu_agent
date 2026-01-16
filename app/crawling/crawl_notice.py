# main.py
import json
import requests
import time
import urllib3
import os
import re
import threading
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

# 모듈 불러오기
from app.crawling.crawl_config import CONFIG
from app.crawling.crawl_parsers import parse_post_content

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 전역 락
file_lock = threading.Lock()

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

class BaseCrawler:
    def __init__(self, target):
        self.dept = target['dept']
        self.detail = target['detail']
        self.base_url = target['url']
        
        safe_dept_name = sanitize_filename(self.dept)
        self.file_path = os.path.join(CONFIG["data_dir"], f"{safe_dept_name}.jsonl")
        
        self.last_crawled_date = CONFIG["cutoff_date"]
        
        self.session = requests.Session()
        self.session.headers.update(CONFIG["headers"])

        self.collected_links = set()
        if os.path.exists(self.file_path):
            with file_lock:
                try:
                    with open(self.file_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            try:
                                data = json.loads(line)
                                if 'url' in data:
                                    self.collected_links.add(data['url'])
                            except: continue
                except Exception as e:
                    pass

    def fetch_page(self, url, referer=None):
        if referer: self.session.headers.update({"Referer": referer})
        try:
            time.sleep(0.5)
            resp = self.session.get(url, verify=False, timeout=30)
            if resp.encoding == 'ISO-8859-1': resp.encoding = resp.apparent_encoding
            return BeautifulSoup(resp.text, 'html.parser')
        except Exception as e:
            print(f"[Error] {self.dept} Fetch Fail: {e}")
            return None

    def save_post(self, post_data):
        if post_data['url'] in self.collected_links: return
        
        with file_lock:
            try:
                with open(self.file_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(post_data, ensure_ascii=False) + "\n")
                self.collected_links.add(post_data['url'])
            except Exception as e:
                print(f"[Save Error] {self.dept}: {e}")

    def process_detail_page(self, title, date, link, referer=None):
        if link in self.collected_links: return
        
        content, images, atts = parse_post_content(self.fetch_page(link, referer), link)
        
        self.save_post({
            "dept": self.dept,
            "detail": self.detail,
            "title": title,
            "date": date,
            "url": link,
            "content": content,
            "images": images,
            "attachments": atts
        })

# ==========================================
# Type A: 일반형
# ==========================================
class TypeACrawler(BaseCrawler):
    def crawl(self):
        page = 1
        while True:
            print(f"[{self.dept}_{self.detail}] Page {page}...")
            
            if '?' in self.base_url:
                url = f"{self.base_url}&page={page}"
            else:
                url = f"{self.base_url}?page={page}"
            
            soup = self.fetch_page(url)
            if not soup: break
            
            rows = soup.select(".board_body tbody tr")
            if not rows: 
                print("   ㄴ 더 이상 게시글이 없습니다.")
                break

            found_regular_post = False

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 4: continue
                
                is_notice = not cols[0].get_text(strip=True).isdigit()
                
                # [수정됨] 1페이지에서는 공지여도 수집합니다! (2페이지부터만 공지 무시)
                if page > 1 and is_notice: continue 

                found_regular_post = True

                title_elem = row.select_one("td.left a")
                if not title_elem: continue
                
                link = urljoin(self.base_url, title_elem['href'])

                for span in title_elem.find_all('span'):
                    span.decompose()
                title = title_elem.get_text(strip=True)
                
                date = cols[3].get_text(strip=True)

                # 1페이지는 무조건 통과 (날짜 검사 안 함)
                if page > 1 and date < self.last_crawled_date:
                    print(f"   ㄴ [Stop] 기준 날짜({self.last_crawled_date}) 도달: {date}")
                    return

                self.process_detail_page(title, date, link)
            
            # 2페이지부터 일반 글이 없으면 종료
            if page > 1 and not found_regular_post:
                print("   ㄴ [End] 일반 게시글 없음. 종료합니다.")
                break
            
            page += 1

# ==========================================
# Type B: 그누보드 (리스트형 포함)
# ==========================================
class TypeBCrawler(BaseCrawler):
    def crawl(self):
        page = 1
        while True:
            print(f"[{self.dept}_{self.detail}] Page {page}...")
            
            if '?' in self.base_url:
                url = f"{self.base_url}&page={page}"
            else:
                url = f"{self.base_url}?page={page}"

            soup = self.fetch_page(url)
            if not soup: break
            
            rows = soup.select(".tbl_head01 tbody tr, .basic_tbl_head tbody tr")
            is_list_style = False
            
            if not rows:
                rows = soup.select(".max_board li, .list_board li, .webzine li")
                if rows: is_list_style = True
            
            if not rows: 
                print("   ㄴ 더 이상 게시글이 없습니다.")
                break
            
            found_regular_post = False

            for row in rows:
                is_notice = False
                
                if is_list_style:
                    if row.select_one(".notice_icon"): is_notice = True
                    
                    link_tag = row.find("a")
                    if not link_tag: continue
                    link = urljoin(self.base_url, link_tag['href'])
                    
                    title_tag = row.select_one("h2") or row.select_one(".subject")
                    if title_tag:
                        for span in title_tag.find_all("span"): span.decompose()
                        title = title_tag.get_text(strip=True)
                    else: title = "No Title"

                    date_tag = row.select_one(".date")
                    date = date_tag.get_text(strip=True) if date_tag else "2025-01-01"

                else:
                    subj_div = row.select_one(".bo_tit a") or row.select_one(".td_subject a")
                    if not subj_div: continue

                    num_elem = row.select_one(".td_num2") or row.select_one(".td_num")
                    if num_elem and not num_elem.get_text(strip=True).isdigit(): is_notice = True
                    if "bo_notice" in row.get("class", []): is_notice = True

                    link = urljoin(self.base_url, subj_div['href'])
                    if "wr_id" not in link and "bo_table" not in link: continue
                    
                    title = subj_div.get_text(strip=True)
                    
                    date_elem = row.select_one(".td_datetime")
                    if not date_elem: continue
                    date = date_elem.get_text(strip=True)
                    if len(date) == 8 and date[2] == '-': date = "20" + date

                # [수정됨] 1페이지에서는 공지여도 수집!
                if page > 1 and is_notice: continue

                found_regular_post = True

                if page > 1 and date < self.last_crawled_date:
                    print(f"   ㄴ [Stop] 기준 날짜({self.last_crawled_date}) 도달: {date}")
                    return

                self.process_detail_page(title, date, link, referer=url)
            
            if page > 1 and not found_regular_post:
                print("   ㄴ [End] 일반 게시글 없음. 종료합니다.")
                break
            
            page += 1

# ==========================================
# Type C: 통합홈페이지
# ==========================================
class TypeCCrawler(BaseCrawler):
    def crawl(self):
        current_url = self.base_url
        page_cnt = 0
        
        while True:
            page_cnt += 1
            print(f"[{self.dept}_{self.detail}] Page {page_cnt}...")
            
            soup = self.fetch_page(current_url)
            if not soup: break
            
            rows = soup.select(".board_list tbody tr")
            if not rows: 
                print("   ㄴ 더 이상 게시글이 없습니다.")
                break

            found_regular_post = False

            for row in rows:
                cols = row.find_all("td")
                if len(cols) < 5: continue
                
                is_notice = not cols[0].get_text(strip=True).isdigit()
                
                # [수정됨] 1페이지에서는 공지여도 수집!
                if page_cnt > 1 and is_notice: continue 
                
                found_regular_post = True

                title = cols[1].get_text(strip=True)
                date = cols[4].get_text(strip=True)
                link_tag = cols[1].find("a")
                
                if not link_tag: continue
                link = urljoin(self.base_url, link_tag['href'])
                
                if page_cnt > 1 and date < self.last_crawled_date:
                    print(f"   ㄴ [Stop] 기준 날짜({self.last_crawled_date}) 도달: {date}")
                    return
                
                self.process_detail_page(title, date, link, referer=current_url)
            
            if page_cnt > 1 and not found_regular_post:
                print("   ㄴ [End] 일반 게시글 없음. 종료합니다.")
                break

            paging = soup.select_one(".paging")
            if paging and paging.find("strong"):
                nxt = paging.find("strong").find_next_sibling("a")
                if nxt: current_url = urljoin(self.base_url, nxt['href'])
                else: break
            else: break

def get_crawler(target):
    url = target['url']
    if "home.knu.ac.kr" in url: return TypeCCrawler(target)
    elif "board.php" in url: return TypeBCrawler(target)
    else: return TypeACrawler(target)

def process(target):
    try:
        crawler = get_crawler(target)
        crawler.crawl()
    except Exception as e:
        print(f"[Fatal] {target['dept']} Error: {e}")

if __name__ == "__main__":
    targets = []
    
    # [수정 핵심] "지금 이 파일(crawl_notice.py)이 있는 폴더"를 찾아냅니다.
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 그 폴더 안에 있는 knu_master.jsonl을 가리킵니다.
    master_file = os.path.join(current_dir, "knu_master.jsonl")
    
    print(f"🚀 [Debug] Master file path: {master_file}")
    
    if os.path.exists(master_file):
        with open(master_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if "dept" in data and "url" in data:
                        if "detail" not in data:
                            data["detail"] = "공지"
                        targets.append(data)
                except Exception as e:
                    print(f"[Skip] JSON Load Error: {e}")
        print(f"Loaded {len(targets)} targets from {master_file}")
    else:
        print(f"[Error] {master_file} not found!")

    if targets:
        print(f"Starting crawler with {CONFIG['max_workers']} workers...")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=CONFIG["max_workers"]) as executor:
            executor.map(process, targets)
            
        end_time = time.time()
        print(f"\nAll tasks completed in {end_time - start_time:.2f} seconds.")
