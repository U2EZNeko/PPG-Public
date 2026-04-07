import os
import re
import time
import requests
import json
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import urllib.parse

# --- Configuration ---
NEGATIVE_PROMPT = "low quality, blurry, distorted"
WIDTH = 512
HEIGHT = 512

# --- Web Scraping Configuration ---
# Using DeepAI's text-to-image generator with cookie support
BASE_URL = "https://deepai.org/machine-learning-model/text2img"
GENERATE_URL = "https://deepai.org/machine-learning-model/text2img"
COOKIES_FILE = "deepai_cookies.json"

# --- Setup Chrome Driver ---
def setup_driver():
    """Setup Chrome driver with appropriate options"""
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.chrome.service import Service
    
    chrome_options = Options()
    
    # Headless mode - enabled by default for automation
    # Uncomment the line below if you want to see the browser window
    # chrome_options.add_argument("--headless")
    
    # Additional headless optimizations
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-gpu")  # Better for headless
    chrome_options.add_argument("--window-size=1920,1080")  # Set window size for headless
    chrome_options.add_argument("--start-maximized")  # Start maximized
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # Use webdriver-manager to automatically download and manage Chrome driver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    print("Chrome driver started in headless mode")
    print("To see the browser window, uncomment '--headless' in setup_driver() function")
    
    return driver

def save_cookies(driver, filename):
    """Save cookies from the current browser session"""
    try:
        cookies = driver.get_cookies()
        with open(filename, 'w') as f:
            json.dump(cookies, f, indent=2)
        print(f"Cookies saved to {filename}")
        return True
    except Exception as e:
        print(f"Failed to save cookies: {e}")
        return False

def load_cookies_from_netscape(driver, filename):
    """Load cookies from Netscape format cookie file"""
    try:
        if not os.path.exists(filename):
            print(f"Cookie file {filename} not found")
            return False
        
        # First navigate to the domain to set cookies
        driver.get("https://deepai.org")
        time.sleep(2)
        
        cookies_added = 0
        with open(filename, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line.startswith('#') or not line or line.startswith('https://'):
                    continue
                
                try:
                    # Parse Netscape cookie format
                    # domain, domain_specified, path, secure, expiry, name, value
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        domain = parts[0]
                        path = parts[2]
                        secure = parts[3] == 'TRUE'
                        expiry = int(parts[4]) if parts[4].isdigit() else None
                        name = parts[5]
                        value = parts[6]
                        
                        # Create cookie object
                        cookie = {
                            'name': name,
                            'value': value,
                            'domain': domain,
                            'path': path,
                            'secure': secure
                        }
                        
                        # Add expiry if valid
                        if expiry and expiry > 0:
                            cookie['expiry'] = expiry
                        
                        try:
                            driver.add_cookie(cookie)
                            cookies_added += 1
                        except Exception as e:
                            print(f"Could not add cookie {name}: {e}")
                            
                except Exception as e:
                    print(f"Error parsing cookie line: {line[:50]}... - {e}")
                    continue
        
        print(f"Loaded {cookies_added} cookies from {filename}")
        return cookies_added > 0
        
    except Exception as e:
        print(f"Failed to load cookies from {filename}: {e}")
        return False

def load_cookies(driver, filename):
    """Load cookies from JSON file and add them to the browser session"""
    try:
        if not os.path.exists(filename):
            print(f"Cookie file {filename} not found")
            return False
        
        with open(filename, 'r') as f:
            cookies = json.load(f)
        
        # First navigate to the domain to set cookies
        driver.get("https://deepai.org")
        time.sleep(2)
        
        # Add each cookie
        for cookie in cookies:
            try:
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"Could not add cookie {cookie.get('name', 'unknown')}: {e}")
        
        print(f"Loaded {len(cookies)} cookies from {filename}")
        return True
    except Exception as e:
        print(f"Failed to load cookies: {e}")
        return False

def setup_authentication(driver):
    """Setup authentication using cookies from cookies.txt"""
    print("Setting up authentication...")
    
    # Load cookies from cookies.txt (Netscape format)
    if load_cookies_from_netscape(driver, "cookies.txt"):
        print("Cookies loaded successfully from cookies.txt!")
        print("Proceeding with image generation...")
        return True
    else:
        print("Failed to load cookies from cookies.txt")
        return False

def generate_image_with_deepai(driver, prompt, negative_prompt=""):
    """Generate image using DeepAI's text-to-image generator"""
    try:
        print(f"Navigating to DeepAI text-to-image generator...")
        driver.get(GENERATE_URL)
        time.sleep(3)
        
        # Wait for the page to load and find prompt-like inputs
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "textarea, input[type='text']"))
        )
        
        # Find and fill the most likely prompt input
        prompt_inputs = driver.find_elements(By.CSS_SELECTOR, "textarea, input[type='text']")
        prompt_input = None

        # Prefer visible textarea or prompt-like placeholders/aria labels
        for input_elem in prompt_inputs:
            if not (input_elem.is_displayed() and input_elem.is_enabled()):
                continue
            try:
                placeholder = (input_elem.get_attribute("placeholder") or "").lower()
                aria_label = (input_elem.get_attribute("aria-label") or "").lower()
                name_attr = (input_elem.get_attribute("name") or "").lower()
                cls = (input_elem.get_attribute("class") or "").lower()
                if any(k in placeholder for k in ["prompt", "describe", "what do you want"]) or \
                   any(k in aria_label for k in ["prompt", "describe"]) or \
                   any(k in name_attr for k in ["prompt", "text"]) or \
                   "prompt" in cls:
                    prompt_input = input_elem
                    break
            except Exception:
                pass

        # Fallback to first visible textarea, then any visible text input
        if not prompt_input:
            for input_elem in prompt_inputs:
                if input_elem.tag_name.lower() == "textarea" and input_elem.is_displayed() and input_elem.is_enabled():
                    prompt_input = input_elem
                    break
        if not prompt_input:
            for input_elem in prompt_inputs:
                if input_elem.is_displayed() and input_elem.is_enabled():
                    prompt_input = input_elem
                    break
        
        if not prompt_input:
            print("Could not find prompt input field")
            return None
        
        # Clear and fill the prompt
        prompt_input.clear()
        prompt_input.send_keys(prompt)
        
        # Set preference to "Quality"
        try:
            print("Setting preference to Quality...")
            quality_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Quality')]")
            for button in quality_buttons:
                if button.is_displayed() and button.is_enabled():
                    # Check if it's already selected
                    if "selected" not in button.get_attribute("class").lower():
                        button.click()
                        print("Quality preference set successfully")
                    else:
                        print("Quality preference already selected")
                    break
        except Exception as e:
            print(f"Could not set quality preference: {e}")
        
        # Set shape to "edit_shape_3"
        try:
            print("Setting shape to edit_shape_3...")
            
            # First, try to expand any shape-related dropdowns or menus
            print("Looking for shape menu to expand...")
            
            # Try to find and click on shape-related expandable elements
            expand_selectors = [
                "//button[contains(@aria-label, 'shape')]",
                "//button[contains(@aria-label, 'Shape')]",
                "//div[contains(@class, 'shape')]//button[contains(@aria-expanded, 'false')]",
                "//button[contains(@class, 'shape') and contains(@aria-expanded, 'false')]",
                "//div[contains(@class, 'shape-selector')]//button",
                "//button[contains(text(), 'Shape')]",
                "//button[contains(text(), 'shape')]",
                "//div[contains(@class, 'shape')]//div[contains(@class, 'dropdown')]//button",
                "//button[contains(@data-testid, 'shape')]"
            ]
            
            menu_expanded = False
            for selector in expand_selectors:
                try:
                    expand_button = driver.find_element(By.XPATH, selector)
                    if expand_button.is_displayed() and expand_button.is_enabled():
                        print(f"Found expandable shape menu: {selector}")
                        expand_button.click()
                        time.sleep(2)  # Wait for menu to expand
                        menu_expanded = True
                        print("Shape menu expanded successfully")
                        break
                except:
                    continue
            
            # If no specific expand button found, try clicking on the shape area to expand
            if not menu_expanded:
                try:
                    shape_areas = driver.find_elements(By.XPATH, "//div[contains(@class, 'shape')]")
                    for area in shape_areas:
                        if area.is_displayed():
                            print("Clicking on shape area to expand...")
                            area.click()
                            time.sleep(2)
                            menu_expanded = True
                            break
                except:
                    pass
            
            # Now try to select the specific shape
            time.sleep(1)  # Brief wait for menu to fully expand
            
            # Try multiple strategies to find and click the edit_shape_3 button
            shape_selectors = [
                "//button[@id='edit_shape_3']",
                "//button[contains(@id, 'edit_shape_3')]",
                "//div[@id='edit_shape_3']",
                "//div[contains(@id, 'edit_shape_3')]",
                "//button[contains(@data-shape, 'edit_shape_3')]",
                "//div[contains(@data-shape, 'edit_shape_3')]",
                "//button[contains(@class, 'edit_shape_3')]",
                "//div[contains(@class, 'edit_shape_3')]"
            ]
            
            shape_selected = False
            for selector in shape_selectors:
                try:
                    shape_button = driver.find_element(By.XPATH, selector)
                    if shape_button.is_displayed() and shape_button.is_enabled():
                        print(f"Found shape button: {selector}")
                        # Check if it's already selected
                        if "selected" not in shape_button.get_attribute("class").lower():
                            shape_button.click()
                            print("Shape edit_shape_3 selected successfully")
                        else:
                            print("Shape edit_shape_3 already selected")
                        shape_selected = True
                        break
                except:
                    continue
            
            # If still no luck, try to find any shape buttons and click the third available one
            if not shape_selected:
                try:
                    all_shape_buttons = driver.find_elements(By.XPATH, "//button[contains(@class, 'shape')]")
                    all_shape_buttons.extend(driver.find_elements(By.XPATH, "//div[contains(@class, 'shape')]//button"))
                    all_shape_buttons.extend(driver.find_elements(By.XPATH, "//button[contains(@data-shape, '')]"))
                    
                    if all_shape_buttons:
                        visible_buttons = [b for b in all_shape_buttons if b.is_displayed() and b.is_enabled()]
                        if len(visible_buttons) >= 3:
                            print(f"Found {len(visible_buttons)} visible shape buttons, clicking the 3rd one...")
                            visible_buttons[2].click()
                            print("3rd shape button clicked (fallback selection)")
                            shape_selected = True
                        elif visible_buttons:
                            print(f"Only {len(visible_buttons)} visible shape button(s) found; clicking last available.")
                            visible_buttons[-1].click()
                            print("Last available shape button clicked (fallback selection)")
                            shape_selected = True
                except Exception as e:
                    print(f"Fallback shape selection failed: {e}")
            
            if not shape_selected:
                print("Could not find or select specific shape edit_shape_3")
                
        except Exception as e:
            print(f"Could not set shape: {e}")
        
        # Try to find and set dimensions if available
        try:
            # Look for dimension inputs (DeepAI might have these)
            dimension_inputs = driver.find_elements(By.CSS_SELECTOR, "input[placeholder*='width'], input[placeholder*='height'], input[type='number']")
            if len(dimension_inputs) >= 2:
                width_input = dimension_inputs[0]
                height_input = dimension_inputs[1]
                
                width_input.clear()
                width_input.send_keys(str(WIDTH))
                height_input.clear()
                height_input.send_keys(str(HEIGHT))
                print(f"Set dimensions to {WIDTH}x{HEIGHT}")
        except Exception as e:
            print(f"Could not set dimensions: {e}")
        
        # Find and click the generate button
        generate_button = None
        # Try multiple button strategies; prefer text that indicates image generation
        button_selectors = [
            "//button[contains(translate(normalize-space(text()), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'generate')]",
            "//button[contains(translate(normalize-space(text()), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'create')]",
            "//button[contains(translate(normalize-space(text()), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'make')]",
            "//button[contains(translate(normalize-space(text()), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'image')]",
            "//button[@type='submit']",
            "//input[@type='submit']"
        ]

        for selector in button_selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for elem in elements:
                    if elem.is_displayed() and elem.is_enabled():
                        generate_button = elem
                        break
                if generate_button:
                    break
            except Exception:
                continue

        if not generate_button:
            print("Could not find generate button")
            return None
        
        print("Clicking generate button...")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", generate_button)
            time.sleep(0.2)
            generate_button.click()
        except Exception:
            # Fallback JS click
            driver.execute_script("arguments[0].click();", generate_button)
        
        print("Image generation started... Waiting for completion...")

        # Capture existing image URLs before generation; we'll wait for a new one
        existing_urls = set()
        try:
            for img in driver.find_elements(By.TAG_NAME, "img"):
                src = (img.get_attribute("src") or "").strip()
                if src.startswith("http"):
                    existing_urls.add(src)
        except Exception:
            pass

        max_wait_time = 120
        start_time = time.time()
        image_url = None

        while time.time() - start_time < max_wait_time:
            try:
                # Prefer result area if present
                candidate_imgs = []
                result_areas = driver.find_elements(By.CSS_SELECTOR, ".try-it-result-area, [class*='result']")
                for area in result_areas:
                    candidate_imgs.extend(area.find_elements(By.TAG_NAME, "img"))
                if not candidate_imgs:
                    candidate_imgs = driver.find_elements(By.TAG_NAME, "img")

                for img in reversed(candidate_imgs):
                    if not img.is_displayed():
                        continue
                    src = (img.get_attribute("src") or "").strip()
                    alt = (img.get_attribute("alt") or "").lower()
                    cls = (img.get_attribute("class") or "").lower()
                    if not src.startswith("http") or src.endswith(".svg"):
                        continue
                    if any(x in src.lower() or x in alt or x in cls for x in ["placeholder", "loading", "spinner", "wait"]):
                        continue
                    # prefer newly appeared image; fallback to any valid long image URL
                    if src not in existing_urls:
                        image_url = src
                        break
                    if len(src) > 80:
                        image_url = src
                if image_url:
                    break
            except Exception:
                pass
            time.sleep(2)
        
        # Check for visible, user-facing generation errors only
        # (avoid false positives from hidden source strings like DEPRECATED_ENDPOINT).
        print("Checking for generation errors...")
        error_detected = False
        error_indicators = ["error", "failed", "unsafe", "blocked", "violation", "policy"]
        benign_indicators = ["deprecated_endpoint", "deprecated", "endpoint"]

        error_selectors = [
            "//div[contains(@class, 'error')]",
            "//div[contains(@class, 'alert')]",
            "//div[contains(@class, 'message')]",
            "//span[contains(@class, 'error')]",
            "//p[contains(@class, 'error')]",
            "//div[contains(@class, 'try-it-result-area')]//*[contains(text(), 'error') or contains(text(), 'Error') or contains(text(), 'failed') or contains(text(), 'Failed')]",
            "//*[contains(@class, 'toast') or contains(@class, 'notification')]"
        ]

        for selector in error_selectors:
            try:
                error_elements = driver.find_elements(By.XPATH, selector)
                for element in error_elements:
                    if not element.is_displayed():
                        continue
                    error_text = (element.text or "").strip()
                    if not error_text:
                        continue
                    lowered = error_text.lower()
                    if any(token in lowered for token in benign_indicators):
                        continue
                    if any(token in lowered for token in error_indicators):
                        print(f"❌ Visible generation error detected: {error_text}")
                        error_detected = True
                        break
                if error_detected:
                    break
            except Exception:
                continue

        if error_detected and not image_url:
            print("Generation failed due to visible error message. Skipping this image.")
            return None

        if image_url:
            print(f"✅ Image URL found: {image_url[:120]}...")
            return image_url

        print("❌ No generated image URL found after waiting.")
        return None
            
    except Exception as e:
        print(f"Error during image generation: {e}")
        return None

def get_image_element(driver):
    """Get the actual generated image element from the try-it-result-area"""
    try:
        print("Looking for generated image in try-it-result-area...")
        
        # First, look specifically in the try-it-result-area
        try:
            result_area = driver.find_element(By.CLASS_NAME, "try-it-result-area")
            print("Found try-it-result-area")
            
            # Look for images within this area
            images_in_area = result_area.find_elements(By.TAG_NAME, "img")
            print(f"Found {len(images_in_area)} images in result area")
            
            for img in images_in_area:
                if img.is_displayed():
                    src = img.get_attribute("src")
                    alt = img.get_attribute("alt") or ""
                    class_name = img.get_attribute("class") or ""
                    
                    # Skip placeholder images
                    if any(placeholder_word in src.lower() or placeholder_word in alt.lower() or placeholder_word in class_name.lower() 
                           for placeholder_word in ["placeholder", "loading", "spinner", "wait"]):
                        print(f"Skipping placeholder image: {src[:50]}...")
                        continue
                    
                    # Look for actual generated images
                    if src and src.startswith("http") and not src.endswith(".svg"):
                        # Check if it's a real image (not a placeholder)
                        if len(src) > 50:  # Real image URLs are usually longer
                            print(f"Found generated image: {src[:100]}...")
                            return img
                        else:
                            print(f"Skipping short URL (likely placeholder): {src}")
            
            print("No valid generated images found in try-it-result-area")
            
        except Exception as e:
            print(f"Error finding try-it-result-area: {e}")
        
        # Fallback: look for generated images with multiple strategies
        print("Trying fallback image detection...")
        image_selectors = [
            "img[src*='generation']",
            "img[src*='output']", 
            "img[src*='result']",
            "img[src*='deepai']",
            "img[src*='cdn']",
            "img[src*='amazonaws']"
        ]
        
        for selector in image_selectors:
            try:
                images = driver.find_elements(By.CSS_SELECTOR, selector)
                for img in images:
                    if img.is_displayed():
                        src = img.get_attribute("src")
                        alt = img.get_attribute("alt") or ""
                        
                        # Skip placeholder images
                        if any(placeholder_word in src.lower() or placeholder_word in alt.lower() 
                               for placeholder_word in ["placeholder", "loading", "spinner", "wait"]):
                            continue
                        
                        if src and src.startswith("http") and not src.endswith(".svg"):
                            print(f"Found image with selector {selector}: {src[:100]}...")
                            return img
            except:
                continue
        
        # Final fallback: look for any image that might be the result
        all_images = driver.find_elements(By.CSS_SELECTOR, "img")
        for img in reversed(all_images):  # Start from last (most recent)
            if img.is_displayed():
                src = img.get_attribute("src")
                alt = img.get_attribute("alt") or ""
                
                # Skip placeholder images
                if any(placeholder_word in src.lower() or placeholder_word in alt.lower() 
                       for placeholder_word in ["placeholder", "loading", "spinner", "wait"]):
                    continue
                
                if src and src.startswith("http") and not src.endswith(".svg"):
                    print(f"Found fallback image: {src[:100]}...")
                    return img
        
        print("No valid images found with any method")
        return None
        
    except Exception as e:
        print(f"Error finding image element: {e}")
        return None

def download_image(driver, image_url, filename):
    """Download image from URL using browser session cookies with improved handling"""
    try:
        print(f"Downloading image from: {image_url}")

        # If URL is not directly fetchable, caller should use browser-save fallback
        if image_url.startswith("blob:") or image_url.startswith("data:"):
            print("Image URL is blob/data URL, cannot fetch with requests directly.")
            return False
        
        # Get cookies from the current browser session
        cookies = driver.get_cookies()
        
        # Create a session with the same cookies
        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
        
        # Set headers to mimic a real browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://deepai.org/',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'image',
            'Sec-Fetch-Mode': 'no-cors',
            'Sec-Fetch-Site': 'same-origin'
        }
        
        # Download the image with proper headers and cookies
        response = session.get(image_url, headers=headers, timeout=30, allow_redirects=True)
        
        if response.status_code == 200:
            # Check if the response actually contains image data
            content_type = response.headers.get('content-type', '').lower()
            if not content_type.startswith('image/'):
                print(f"Warning: Response is not an image (Content-Type: {content_type})")
                # Try to save anyway in case it's a mislabeled image
                if len(response.content) > 1000:  # Check if content is substantial
                    with open(filename, "wb") as f:
                        f.write(response.content)
                    print(f"Image saved as {filename} (despite content-type warning)")
                    return True
                else:
                    print("Response content too small, likely not an image")
                    return False
            
            # Save the image
            with open(filename, "wb") as f:
                f.write(response.content)
            
            # Verify the file was created and has content
            if os.path.exists(filename) and os.path.getsize(filename) > 1000:
                print(f"✅ Image saved successfully: {filename}")
                print(f"   File size: {os.path.getsize(filename)} bytes")
                return True
            else:
                print(f"❌ File saved but appears corrupted or empty")
                return False
        else:
            print(f"❌ Failed to download image: HTTP {response.status_code}")
            print(f"   Response: {response.text[:200]}...")
            return False
            
    except Exception as e:
        print(f"❌ Error downloading image: {e}")
        return False

def save_image_from_browser(driver, filename):
    """Save image directly from browser using screenshot method"""
    try:
        print("Attempting to save image directly from browser...")
        
        # Get the image element
        img_element = get_image_element(driver)
        if not img_element:
            print("Could not find image element to save")
            return False
        
        # Scroll to the image to ensure it's visible
        driver.execute_script("arguments[0].scrollIntoView(true);", img_element)
        time.sleep(1)
        
        # Get image dimensions
        width = img_element.size['width']
        height = img_element.size['height']
        
        print(f"Image dimensions: {width}x{height}")
        
        # Take screenshot of the specific image element
        img_element.screenshot(filename)
        
        # Verify the file was created
        if os.path.exists(filename) and os.path.getsize(filename) > 1000:
            print(f"✅ Image saved from browser: {filename}")
            print(f"   File size: {os.path.getsize(filename)} bytes")
            return True
        else:
            print(f"❌ Browser screenshot failed or file corrupted")
            return False
            
    except Exception as e:
        print(f"❌ Error saving from browser: {e}")
        return False

def main():
    """Main function"""
    print("DeepAI Text-to-Image Generator with Cookie Authentication")
    print("="*55)
    print("Using DeepAI's text-to-image generator with login support")
    print("Cookies will be saved for future use to avoid re-login")
    print("="*55)
    
    # Get user input
    positive_prompt = input("Enter the prompt for image generation: ").strip()
    try:
        num_images = int(input("Enter the number of images to generate: ").strip())
    except ValueError:
        print("Number of images must be an integer.")
        return
    
    # Setup driver
    driver = setup_driver()
    
    try:
        # Setup authentication (cookies or manual login)
        if not setup_authentication(driver):
            print("Authentication failed. Exiting...")
            return
        
        # Prepare base filename and ensure input folder exists
        safe_prompt = re.sub(r'[^a-zA-Z0-9_\- ]', '_', positive_prompt).strip()[:100]
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        # Ensure input folder exists
        input_folder = "input"
        if not os.path.exists(input_folder):
            os.makedirs(input_folder)
            print(f"Created {input_folder} folder")
        
        # Generate images
        for i in range(num_images):
            print(f"\nGenerating image {i+1} of {num_images}...")
            
            image_url = generate_image_with_deepai(
                driver, 
                positive_prompt, 
                NEGATIVE_PROMPT
            )
            
            if image_url:
                filename = os.path.join(input_folder, f"{safe_prompt}_{timestamp}_{i+1}.jpg")
                if download_image(driver, image_url, filename):
                    print(f"✅ Successfully generated and saved: {filename}")
                else:
                    print(f"⚠️ Direct download failed for image {i+1}, trying browser save fallback...")
                    if save_image_from_browser(driver, filename):
                        print(f"✅ Successfully saved via browser fallback: {filename}")
                    else:
                        print(f"❌ Failed to save image {i+1}")
                        print("The image may be temporarily unavailable or require manual download")
            else:
                print(f"❌ Failed to generate image {i+1}")
                print("This could be due to:")
                print("  - Content policy violations")
                print("  - Generation errors")
                print("  - Network issues")
                print("  - Service limitations")
                
                # Automatically retry after 5 seconds
                if i < num_images - 1:
                    print("Waiting 5 seconds before retrying...")
                    time.sleep(5)
                    
                    print(f"Retrying image {i+1}...")
                    retry_image_url = generate_image_with_deepai(
                        driver, 
                        positive_prompt, 
                        NEGATIVE_PROMPT
                    )
                    
                    if retry_image_url:
                        filename = os.path.join(input_folder, f"{safe_prompt}_{timestamp}_{i+1}.jpg")
                        if download_image(driver, retry_image_url, filename):
                            print(f"✅ Retry successful! Generated and saved: {filename}")
                        else:
                            print(f"⚠️ Retry direct download failed for image {i+1}, trying browser save fallback...")
                            if save_image_from_browser(driver, filename):
                                print(f"✅ Retry fallback successful! Saved: {filename}")
                            else:
                                print(f"❌ Retry failed to save image {i+1}")
                    else:
                        print(f"❌ Retry failed for image {i+1}")
                        print("Moving to next image...")
            
            # Wait between generations to avoid rate limiting
            if i < num_images - 1:
                print("Waiting for 15 seconds before next generation...")
                time.sleep(15)

        print("\nAll done!")
        print(f"Generated images saved to: {input_folder}/")
        print("Note: If some images couldn't be downloaded automatically,")
        print("check the browser for generated images and download them manually.")
        
    except KeyboardInterrupt:
        print("\nScript interrupted by user.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Close browser automatically
        print("Closing browser...")
        driver.quit()
        print("Browser closed.")

if __name__ == "__main__":
    main()
