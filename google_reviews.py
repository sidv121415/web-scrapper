import os
import time
import re
from datetime import datetime
import pandas as pd
import urllib.parse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.keys import Keys

# Utility to validate key names
def is_clean_key(k):
    base_key = k.split("_")[0]
    return (
        len(base_key) > 3 and
        ".." not in base_key and
        not base_key.endswith("…") and
        not base_key.endswith(".") and
        not re.search(r"[.…]{2,}", base_key)
    )

def is_number(value):
    return bool(re.match(r"^\d+(\.\d+)?(\/\d+)?$", value.strip()))

def construct_google_maps_url(restaurant_name, location):
    base_url = "https://www.google.com/maps/search/"
    query = f"{restaurant_name} {location}".replace(" ", "+")
    return base_url + urllib.parse.quote(query)

def wait_for_new_reviews(driver, prev_count, timeout=10):
    """
    Wait up to `timeout` seconds for new reviews to load,
    returns the new count of reviews found.
    """
    start = time.time()
    while time.time() - start < timeout:
        current_reviews = driver.find_elements(By.CSS_SELECTOR, "div.jftiEf")
        if len(current_reviews) > prev_count:
            return len(current_reviews)
        time.sleep(1)
    return prev_count

def scrape_google_reviews(restaurant_name, location):
    options = webdriver.ChromeOptions()
    options.add_argument("--lang=en-US")
    #options.add_argument("--headless")  # Uncomment if you want headless mode
    options.add_argument("--disable-notifications")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    driver = webdriver.Chrome(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    search_url = construct_google_maps_url(restaurant_name, location)
    driver.get(search_url)

    try:
        WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable(
                (By.XPATH, '//button[contains(., "I agree") or contains(., "Accept all")]'))
        ).click()
        time.sleep(1)
    except TimeoutException:
        pass

    try:
        if "https://www.google.com/maps/place/" not in driver.current_url:
            first_result = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.Nv2PK.tH5CWc.THOPZb a"))
            )
            driver.get(first_result.get_attribute("href"))
            time.sleep(3)
    except TimeoutException:
        print("❌ Couldn't find the restaurant.")
        driver.quit()
        return pd.DataFrame()

    try:
        WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, '//button[contains(., "Reviews")]'))
        ).click()
        time.sleep(3)

        # Sort by "Newest"
        try:
            sort_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//button[@aria-label="Sort reviews"]'))
            )
            driver.execute_script("arguments[0].click();", sort_button)
            time.sleep(1)

            newest_option = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//div[@role="menuitemradio" and .//div[text()="Newest"]]'))
            )
            driver.execute_script("arguments[0].click();", newest_option)
            time.sleep(2)
        except TimeoutException:
            print("⚠️ Could not apply 'Newest' sorting — continuing.")
    except TimeoutException:
        print("❌ Couldn't open reviews.")
        driver.quit()
        return pd.DataFrame()

    def element_exists(parent, selector):
        try:
            parent.find_element(By.CSS_SELECTOR, selector)
            return True
        except:
            return False

    def get_total_reviews_count():
        try:
            container = driver.find_element(By.CSS_SELECTOR, "div.jANrlb")
            text = container.text  # e.g. "4.0\n16,301 reviews"
            match = re.search(r"([\d,]+)\s*reviews", text)
            if match:
                return int(match.group(1).replace(',', ''))
        except Exception as e:
            print(f"⚠️ Could not get total review count: {e}")
        return None

    total_reviews = get_total_reviews_count()
    if total_reviews:
        print(f"📊 Expected total reviews: {total_reviews:,}")

    reviews = []
    metadata_keys = set()

    print("🔄 Starting review collection...")

    while True:
        current_reviews = driver.find_elements(By.CSS_SELECTOR, "div.jftiEf")

        # Process new reviews only
        for i in range(len(reviews), len(current_reviews)):
            try:
                review = current_reviews[i]
                review_id = review.get_attribute("data-review-id") or str(i)

                reviewer_info = review.find_element(By.CSS_SELECTOR, "div.RfnDt").text if element_exists(review, "div.RfnDt") else ""
                is_local_guide = "Y" if "Local Guide" in reviewer_info else "N"
                num_reviews = ""
                if "·" in reviewer_info:
                    parts = [p.strip() for p in reviewer_info.split("·")]
                    for part in parts:
                        if "review" in part.lower():
                            num_reviews = part.split()[0]
                            break

                if element_exists(review, "button.w8nwRe"):
                    driver.execute_script("arguments[0].click();", review.find_element(By.CSS_SELECTOR, "button.w8nwRe"))
                    time.sleep(0.2)

                review_text = review.find_element(By.CSS_SELECTOR, "span.wiI7pd").text if element_exists(review, "span.wiI7pd") else ""
                rating_elem = review.find_element(By.CSS_SELECTOR, "span.kvMYJc")
                rating_text = rating_elem.get_attribute("aria-label")
                rating = rating_text.split(" ")[0] if rating_text else ""

                owner_response = "None"
                if element_exists(review, "div.CDe7pd"):
                    owner_block = review.find_element(By.CSS_SELECTOR, "div.CDe7pd")
                    if element_exists(owner_block, "button.w8nwRe"):
                        driver.execute_script("arguments[0].click();", owner_block.find_element(By.CSS_SELECTOR, "button.w8nwRe"))
                        time.sleep(0.2)
                    owner_response = owner_block.text

                metadata = {}

                for item in review.find_elements(By.CSS_SELECTOR, "div.PBK6be"):
                    try:
                        key_elem = item.find_element(By.CSS_SELECTOR, "span.RfDO5c > span[style*='font-weight']")
                        key = key_elem.text.strip(':').strip()
                        value_elem = item.find_elements(By.CSS_SELECTOR, "span.RfDO5c")[-1]
                        value = value_elem.text.strip()
                        if is_clean_key(key):
                            if key.lower() == "service":
                                if is_number(value):
                                    metadata["service"] = value
                                    metadata_keys.add("service")
                                else:
                                    metadata["service_type"] = value
                                    metadata_keys.add("service_type")
                            else:
                                metadata[key] = value
                                metadata_keys.add(key)
                    except:
                        continue

                for b_tag in review.find_elements(By.CSS_SELECTOR, "span > b"):
                    try:
                        full_text = b_tag.find_element(By.XPATH, "..").text
                        if ":" in full_text:
                            key, val = map(str.strip, full_text.split(":", 1))
                            if is_clean_key(key):
                                if key.lower() == "service":
                                    if is_number(val):
                                        metadata["service"] = val
                                        metadata_keys.add("service")
                                    else:
                                        metadata["service_type"] = val
                                        metadata_keys.add("service_type")
                                else:
                                    metadata[key] = val
                                    metadata_keys.add(key)
                    except:
                        continue

                data = {
                    "review_id": review_id,
                    "reviewer_name": review.find_element(By.CSS_SELECTOR, "div.d4r55").text,
                    "review_date": review.find_element(By.CSS_SELECTOR, "span.rsqaWe").text,
                    "rating": rating,
                    "review_text": review_text,
                    "num_reviews": num_reviews,
                    "local_guide": is_local_guide,
                    "owner_response": owner_response,
                    "scrape_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                data.update(metadata)
                reviews.append(data)
            except Exception as e:
                print(f"⚠️ Error processing review {i}: {str(e)}")
                continue

        if total_reviews:
            if len(reviews) >= total_reviews:
                print(f"✅ Collected all expected {total_reviews} reviews.")
                break
        else:
            # Wait for new reviews to load before breaking
            new_count = wait_for_new_reviews(driver, len(reviews), timeout=10)
            if new_count == len(reviews):
                print(f"ℹ️ No new reviews after waiting — assuming all loaded.")
                break

        # Scroll reviews container to load more
        try:
            scroll_container = driver.find_element(By.CSS_SELECTOR, "div.m6QErb.DxyBCb.kA9KIf.dS8AEf")
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scroll_container)
            time.sleep(2)
        except Exception as e:
            print(f"⚠️ Scroll error: {e}")
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)

    print(f"📊 Final count: {len(reviews)} reviews collected")

    metadata_keys = {k for k in metadata_keys if is_clean_key(k)}

    for review in reviews:
        for key in metadata_keys:
            if key not in review:
                review[key] = "No data"

    driver.quit()

    valid_keys = {
        "review_id", "reviewer_name", "review_date", "rating", "review_text",
        "num_reviews", "local_guide", "owner_response", "scrape_timestamp"
    }.union(metadata_keys)

    reviews_df = pd.DataFrame(reviews)
    reviews_df = reviews_df[[col for col in reviews_df.columns if col in valid_keys]]
    return reviews_df


def scrape_and_save(restaurant_name, location):
    print(f"\n🔍 Starting scrape for '{restaurant_name}' in '{location}'...")
    reviews_df = scrape_google_reviews(restaurant_name, location)
    if reviews_df.empty:
        print(f"❌ No reviews scraped for '{restaurant_name}' in '{location}'.")
        return False
    safe_name = restaurant_name.replace(" ", "_").lower()
    safe_location = location.replace(" ", "_").lower()
    file_pattern = f"reviews_{safe_name}_{safe_location}"
    reviews_dir = "reviews_data"
    os.makedirs(reviews_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_filename = f"{file_pattern}_{timestamp}.xlsx"
    excel_path = os.path.join(reviews_dir, excel_filename)
    reviews_df.to_excel(excel_path, index=False)
    print(f"✅ Successfully scraped {len(reviews_df)} reviews for '{restaurant_name}'. Saved to:\n📊 {excel_path}")
    return True


def main():
    input_file = "list restaurant.txt"
    # This regex expects lines like "1. Sangeetha Veg Restaurant, T Nagar (Chennai)"
    pattern = re.compile(r'\d+\.\s*(.*?),\s*(.*?)\s*\((.*?)\)')
    jobs = []

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            match = pattern.match(line)
            if match:
                rest_name = match.group(1).strip()
                area = match.group(2).strip()
                city = match.group(3).strip()
                location = f"{area} {city}"
                jobs.append((rest_name, location))
            else:
                print(f"⚠️ Skipping invalid line: {line}")

    print(f"\nTotal restaurants to scrape: {len(jobs)}")

    for rest_name, location in jobs:
        try:
            scrape_and_save(rest_name, location)
        except Exception as e:
            print(f"❌ Error scraping '{rest_name}' in '{location}': {e}")

    print("\n🎉 All scraping tasks completed.")


if __name__ == "__main__":
    main()
