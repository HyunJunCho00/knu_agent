import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import pandas as pd
import random

# ==============================================================================
# 1. 팝업 HTML 파싱 함수
# ==============================================================================
def parse_syllabus_html(html_source):
    soup = BeautifulSoup(html_source, 'html.parser')
    result = {}
    
    # 평가 비율 추출
    eval_map = {
        "출석": "popupContent_frmInputEvltnRate1",
        "중간고사": "popupContent_frmInputEvltnRate2",
        "기말고사": "popupContent_frmInputEvltnRate3",
        "과제": "popupContent_frmInputEvltnRate4",
        "발표": "popupContent_frmInputEvltnRate5",
        "토론": "popupContent_frmInputEvltnRate6",
        "기타": "popupContent_frmInputEvltnRate9",
        "총점": "popupContent_frmInputTotalScre"
    }
    
    for key, element_id in eval_map.items():
        tag = soup.find("input", {"id": element_id})
        if tag and tag.has_attr('value') and tag['value']:
            try:
                val = int(tag['value'])
                if val > 0: result[key] = val
            except: pass

    # 상세 설명
    detail_tag = soup.find("textarea", {"id": "popupContent_frmTextATab3_01"})
    if detail_tag:
        result["평가상세"] = detail_tag.text.strip()[:100]
        
    return result

# ==============================================================================
# 2. 메인 크롤링 로직
# ==============================================================================
async def run_scraper():
    async with async_playwright() as p:
        # headless=False: 브라우저가 뜨는 것을 직접 확인
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()
        page.set_default_timeout(10000)
        
        print("🚀 페이지 접속 중...")
        await page.goto("https://sy.knu.ac.kr/_make/lect/lect_list.php")
        await page.wait_for_load_state("networkidle")

        # ---------------------------------------------------------
        # [Step 1] 검색 조건 설정 (2025-1)
        # ---------------------------------------------------------
        print("⚙️ 검색 조건 설정 (2025-1)...")
        await page.fill("#schEstblYear___input", "2025")
        await page.press("#schEstblYear___input", "Enter")
        await page.wait_for_timeout(1000)

        # 학기 강제 선택
        await page.evaluate("document.querySelector('#schEstblSmstrSctcd').value = 'CMmn010.0010'") 
        
        # 검색 버튼 클릭
        print("🔍 검색 버튼 클릭...")
        await page.click("input#btnSearch")
        
        # 로딩 대기 (로딩바 사라질 때까지)
        try:
            await page.locator("#__progressModal").wait_for(state="hidden", timeout=5000)
        except: pass
        await page.wait_for_timeout(2000)

        # ---------------------------------------------------------
        # [Step 2] "진짜 행"과 "강의명 컬럼" 찾기 (핵심 디버깅)
        # ---------------------------------------------------------
        # WebSquare의 가짜 행(display:none)을 거르고 진짜 행만 찾음
        visible_rows = await page.locator("#grid01_body_table tr:visible").all()
        
        if not visible_rows:
            print("❌ 로딩된 데이터가 없습니다.")
            await browser.close()
            return

        print(f"\n✅ 화면에 보이는 실제 데이터 행 개수: {len(visible_rows)}개")

        # 첫 번째 진짜 행의 모든 컬럼 텍스트를 찍어봄 (인덱스 확인용)
        first_row = visible_rows[0]
        cells = await first_row.locator("td").all()
        
        print("\n📊 [컬럼 인덱스 지도]")
        target_col_index = -1
        
        for idx, cell in enumerate(cells):
            text = await cell.inner_text()
            print(f"  Index {idx}: {text}")
            # '대학'이나 '전공' 같은 단어가 아니고, 길이가 좀 긴 것이 강의명일 확률 높음
            # 혹은 text가 '대학'이 들어간 '일반선택' 다음 컬럼이 강의명일 것임.
            if "대학" in text: # 예: "대학수학" 등.. 이건 강의명일수도 있지만 보통 인덱스 5번이 강의명
                pass
        
        # [중요] 사용자가 직접 확인하고 수정할 수 있도록 로그 보고 판단
        # 보통 WebSquare 구조상:
        # 0: No, 1: ?, 2: 대학, 3: 학부, 4: 이수구분(일반선택), 5: 교과목명(대학영어)
        target_col_index = 5  # <--- 아까 4번이 '일반선택'이었으니 5번으로 변경!
        print(f"\n🎯 '교과목명' 추정 인덱스: {target_col_index} (여기를 클릭합니다)")

        # ---------------------------------------------------------
        # [Step 3] 상세 수집 시작
        # ---------------------------------------------------------
        results = []

        # 상위 3개만 테스트
        for i, row in enumerate(visible_rows[:3]): 
            try:
                # 타겟 셀(강의명) 찾기
                target_cell = row.locator("td").nth(target_col_index)
                course_name = await target_cell.inner_text()
                
                print(f"\n[{i+1}] '{course_name}' 공략 중...")

                # ⚡ 팝업 리스너
                async with page.expect_popup() as popup_info:
                    # 셀 내부의 텍스트 요소(nobr)를 직접 클릭해야 정확함
                    # 텍스트 요소가 없으면 셀 중앙 클릭
                    text_el = target_cell.locator("nobr, div")
                    if await text_el.count() > 0:
                        await text_el.first.dblclick(force=True)
                    else:
                        box = await target_cell.bounding_box()
                        if box:
                            await page.mouse.dblclick(box['x'] + box['width']/2, box['y'] + box['height']/2)

                # 팝업 핸들링
                popup = await popup_info.value
                await popup.wait_for_load_state("networkidle")
                
                # 내용 로딩 대기 (총점 입력칸이 뜰 때까지)
                try:
                    await popup.locator("#popupContent_frmInputTotalScre").wait_for(state="visible", timeout=3000)
                except:
                    print("  ⚠️ 내용 로딩 시간 초과 (빈 화면 가능성)")

                # 데이터 추출
                html = await popup.content()
                data = parse_syllabus_html(html)
                data['교과목명'] = course_name
                
                print(f"  ✅ 수집 성공: {data.get('평가비율')}")
                results.append(data)

                await popup.close()
                await asyncio.sleep(1) 

            except Exception as e:
                print(f"  ❌ 실패: {e}")

        await browser.close()
        
        if results:
            df = pd.DataFrame(results)
            print("\n" + "="*50)
            print(df)
            df.to_csv("knu_syllabus_final.csv", index=False, encoding="utf-8-sig")

if __name__ == "__main__":
    asyncio.run(run_scraper())