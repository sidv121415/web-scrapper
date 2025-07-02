import os
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
import pandas as pd
import urllib.parse

def construct_google_maps_url(restaurant_name, location):
    """Construct Google Maps search URL"""
    base_url = "https://www.google.com/maps/search/"
    query = f"{restaurant_name} {location}".replace(" ", "+")
    return base_url + urllib.parse.quote(query)

def scrape_google_reviews(restaurant_name, location, max_reviews=1500):
    # Construct search URL
    search_url = construct_google_maps_url(restaurant_name, location)
    
    # Setup Chrome options
    options = webdriver.ChromeOptions()
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-notifications")
    options.add_argument("--window-size=1920,1080")
    
    # Initialize driver
    driver = webdriver.Chrome(options=options)
    driver.get(search_url)
    
    # Accept cookies if present
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, '//button[contains(., "I agree") or contains(., "Accept all")]'))
        ).click()
        time.sleep(1)
    except:
        pass

    # Detect whether on business page or search results page
    current_url = driver.current_url
    if "https://www.google.com/maps/place/" in current_url:
        print("✅ Directly on business page.")
        time.sleep(3)
    else:
        try:
            print("ℹ️ Multiple results found. Clicking the first result...")
            first_result = WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.Nv2PK.tH5CWc.THOPZb a"))
            )
            business_url = first_result.get_attribute("href")
            driver.get(business_url)
            time.sleep(3)
        except TimeoutException:
            print("❌ Error: Couldn't find the restaurant in search results.")
            driver.quit()
            return pd.DataFrame()

    # Click Reviews tab
    try:
        reviews_button = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, '//button[contains(., "Reviews")]'))
        )
        reviews_button.click()
        time.sleep(3)
    except TimeoutException:
        print("❌ Error: Couldn't find Reviews button")
        driver.quit()
        return pd.DataFrame()

    # Element existence check
    def element_exists(parent, selector):
        try:
            parent.find_element(By.CSS_SELECTOR, selector)
            return True
        except:
            return False

    # Scroll review section
    def scroll_reviews_section():
        try:
            scroll_container = driver.find_element(By.CSS_SELECTOR, "div.m6QErb.DxyBCb.kA9KIf.dS8AEf")
            last_height = driver.execute_script("return arguments[0].scrollHeight", scroll_container)
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scroll_container)
            time.sleep(2)
            new_height = driver.execute_script("return arguments[0].scrollHeight", scroll_container)
            return new_height != last_height
        except Exception as e:
            print(f"Scroll error: {str(e)}")
            return False

    # Main scraping loop
    reviews = []
    last_review_count = 0
    scroll_attempts = 0
    max_scroll_attempts = 400

    while len(reviews) < max_reviews and scroll_attempts < max_scroll_attempts:
        scroll_attempts += 1
        current_reviews = driver.find_elements(By.CSS_SELECTOR, "div.jftiEf")

        for i in range(len(reviews), len(current_reviews)):
            try:
                review = current_reviews[i]
                review_id = review.get_attribute("data-review-id") or str(i)

                if review_id not in [r.get('review_id', '') for r in reviews]:
                    reviewer_info = review.find_element(By.CSS_SELECTOR, "div.RfnDt").text if element_exists(review, "div.RfnDt") else ""
                    is_local_guide = "Y" if "Local Guide" in reviewer_info else "N"
                    num_reviews = ""
                    if "·" in reviewer_info:
                        parts = [p.strip() for p in reviewer_info.split("·")]
                        for part in parts:
                            if "review" in part.lower():
                                num_reviews = part.split()[0]
                                break

                    owner_response = "None"
                    if element_exists(review, "div.CDe7pd"):
                        owner_response = review.find_element(By.CSS_SELECTOR, "div.CDe7pd").text

                    data = {
                        "review_id": review_id,
                        "reviewer_name": review.find_element(By.CSS_SELECTOR, "div.d4r55").text,
                        "review_date": review.find_element(By.CSS_SELECTOR, "span.rsqaWe").text,
                        "rating": review.find_element(By.CSS_SELECTOR, "span.kvMYJc").get_attribute("aria-label")[0],
                        "review_text": review.find_element(By.CSS_SELECTOR, "span.wiI7pd").text if element_exists(review, "span.wiI7pd") else "",
                        "num_reviews": num_reviews,
                        "local_guide": is_local_guide,
                        "owner_response": owner_response,
                        "scrape_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    reviews.append(data)
                    if len(reviews) >= max_reviews:
                        break
            except Exception as e:
                print(f"Skipping review due to error: {str(e)}")
                continue

        if not scroll_reviews_section():
            print("⚠️ No more reviews loading, ending scroll.")
            break
        if len(current_reviews) == last_review_count:
            print("⚠️ No new reviews loaded after scroll.")
            break
        last_review_count = len(current_reviews)

    driver.quit()
    return pd.DataFrame(reviews)

if __name__ == "__main__":
    restaurant_name = input("Enter restaurant name: ").strip()
    location = input("Enter location (city/area): ").strip()
    
    print(f"\nScraping reviews for {restaurant_name} in {location}...")
    reviews_df = scrape_google_reviews(restaurant_name, location)

    if not reviews_df.empty:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c for c in restaurant_name if c.isalnum() or c in (' ', '_')).rstrip()
        filename = f"reviews_{safe_name}_{timestamp}.csv"
        
        os.makedirs("reviews_data", exist_ok=True)
        filepath = os.path.join("reviews_data", filename)
        
        reviews_df.to_csv(filepath, index=False, encoding='utf-8-sig')
        print(f"\n✅ Successfully scraped {len(reviews_df)} reviews")
        print(f"📄 Data saved to: {filepath}")
        print("\n🔍 Sample data:")
        print(reviews_df.head())
    else:
        print("\n❌ Failed to scrape any reviews. Please check:")
        print("- Restaurant name and location are correct")
        print("- The business exists on Google Maps")
        print("- You're not blocked by Google")
        print("- Try running the script again")
