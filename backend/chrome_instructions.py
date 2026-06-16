"""
Generates the self-contained instruction string sent to Claude in Chrome
for a full Reviews Intelligence audit.
"""


def build_chrome_instruction(
    brand: str,
    base_url: str,
    scan_id: str,
    webhook_url: str,
    webhook_secret: str,
) -> str:
    return f"""You are conducting a professional reviews audit of {brand} ({base_url}) \
for Yotpo's sales team. You have access to a real Chrome browser. Follow these \
instructions exactly and completely.

WEBHOOK: When you finish, POST your findings to:
  {webhook_url}/api/browser-data/{scan_id}
  Header: X-Webhook-Secret: {webhook_secret}
  Content-Type: application/json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1: HOMEPAGE AUDIT (2 minutes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Navigate to {base_url}

a) Dismiss any cookie banners, GDPR popups, email capture modals, or chat widgets
   immediately. Click X, Close, Accept, or Decline — whatever closes them fastest.

b) Look at the navigation. Note whether there is a link to "Reviews" or "Testimonials".

c) Identify what review platform they use. Look in page source for: yotpo, bazaarvoice,
   bvstatic, powerreviews, okendo, stamped, judgeme, loox, trustpilot. Note which one.

d) Find links to product pages. Look for:
   - A "Shop" or "Products" section in nav
   - Featured/bestseller products on homepage
   - Any link containing /products/, /shop/, /collections/ followed by a product name
   Collect at least 5 product page URLs.
   If you can't find 5 from the homepage, click into the main shop/products section.

e) Take a screenshot of the homepage.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2: PRODUCT PAGE AUDITS (5 minutes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Visit each of the 5 product pages you found. For EACH product page:

a) Dismiss any popups immediately.

b) Note the product name and URL.

c) Look for star ratings at the top of the page (above the fold, before scrolling).
   Note: visible or not visible.

d) Scroll slowly down the entire page. Look for a reviews section. It may be labeled
   "Reviews", "Customer Reviews", "Ratings & Reviews", or similar.

e) Once you find the reviews section:
   - Note the TOTAL review count displayed (e.g. "847 reviews", "4.6 out of 5 based on 234 ratings")
   - Read and copy the text of the first 5 visible reviews verbatim
   - Note the date of the most recent review
   - Note whether customer photos are visible
   - Note whether video reviews are visible
   - Note whether there is an AI-generated summary above the reviews
   - Check if reviews are longer than 2-3 sentences or mostly 1-2 word ratings

f) If there is a "Load More Reviews" button, click it once and wait for more to load.

g) Scroll back to top and take a screenshot of the page above the fold.

h) Scroll to the reviews section and take a screenshot of the reviews.

i) Check the page source for JSON-LD schema. Look for @type: "Review" or
   @type: "AggregateRating". Note if found.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3: BESTSELLER AUDIT (2 minutes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Find the brand's best-selling products. Try these in order:
  {base_url}/collections/best-sellers
  {base_url}/collections/bestsellers
  {base_url}/collections/best-selling
  Navigation menu → "Best Sellers"
  Homepage featured/bestseller section

Visit the top 5 bestselling products. For each one, note:
  - Product name
  - URL
  - Total review count displayed on the page
  - Whether it has 50 or more reviews

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4: CATEGORY PAGE AUDIT (1 minute)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Navigate to the main shop/collection page.
Try: {base_url}/collections/all  (or find it via navigation)

Look at the product grid/listing:
- Do product cards show star ratings?
- Do they show review counts like "(234)"?
- Take a screenshot of the product grid.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5: PAGE SPEED (1 minute)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Open a new tab and go to: https://pagespeed.web.dev/
Enter the URL of the first product page you visited. Select MOBILE analysis.
Click Analyze and wait for results.

Record:
- Performance score (0-100)
- Largest Contentful Paint (LCP) in milliseconds
- First Contentful Paint (FCP) in milliseconds
- Total Blocking Time (TBT) in milliseconds

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6: POST DATA TO WEBHOOK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Compile everything into this EXACT JSON structure and POST it:

{{
  "scan_id": "{scan_id}",
  "brand": "{brand}",
  "base_url": "{base_url}",
  "audited_at": "<ISO timestamp>",
  "mode": "chrome",
  "pdps_visited": [
    {{
      "url": "<product URL>",
      "product_name": "<name>",
      "reviews": [
        {{
          "text": "<full review text>",
          "word_count": <number>,
          "date": "<date string>",
          "has_photo": <true/false>,
          "has_video": <true/false>,
          "rating": <1-5>
        }}
      ],
      "total_review_count": <number or null>,
      "avg_rating": <number or null>,
      "has_ai_summary": <true/false>,
      "ai_summary_text": "<text or empty string>",
      "stars_above_fold": <true/false>,
      "has_review_schema": <true/false>,
      "has_aggregate_rating_schema": <true/false>,
      "review_platform_detected": "<platform name or empty>",
      "screenshot_base64": "<data:image/png;base64,... or empty string>"
    }}
  ],
  "category_page": {{
    "url": "<category URL>",
    "has_stars_on_cards": <true/false>,
    "screenshot_base64": "<base64 or empty string>"
  }},
  "bestsellers": [
    {{
      "url": "<URL>",
      "product_name": "<name>",
      "review_count": <number or null>,
      "has_50_plus": <true/false>
    }}
  ],
  "homepage": {{
    "detected_platform": "<platform or empty>",
    "has_nav_review_link": <true/false>,
    "screenshot_base64": "<base64 or empty string>"
  }},
  "llm_probe": {{
    "quote_question": "Please quote the exact text of the first customer review on {base_url}",
    "quote_response": "<what Claude/AI says when asked>",
    "can_quote": <true/false>,
    "complaint_question": "What is the most common complaint in reviews on {base_url}?",
    "complaint_response": "<response>"
  }},
  "page_speed": {{
    "url_tested": "<URL>",
    "score": <0-100>,
    "lcp_ms": <milliseconds>,
    "fcp_ms": <milliseconds>,
    "tbt_ms": <milliseconds>
  }},
  "vertical_signals": {{
    "detected_vertical": "<beauty|apparel|home|food|pet|other>",
    "signals_found": ["<signal1>", "<signal2>"],
    "true_to_size_mentions": <number>
  }},
  "rich_snippets": {{
    "has_review_schema": <true/false>,
    "has_aggregate_rating": <true/false>,
    "schema_types_found": ["<type1>"]
  }},
  "audit_notes": ["<any notes about issues, bot detection, popups>"]
}}

POST this to: {webhook_url}/api/browser-data/{scan_id}
Header: X-Webhook-Secret: {webhook_secret}
Header: Content-Type: application/json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMPORTANT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Never skip a step. Complete all 6 steps.
- If a page fails to load, try once more then move on and note the error.
- Dismiss ALL popups before doing anything else on each page.
- Copy review text verbatim — do not paraphrase or summarize.
- Review counts must be the exact number shown on the page — do not estimate.
- If bot detection blocks a page, note it and try a different product page.
- Never fabricate data. If you cannot find something, use null or empty string.
- Complete the webhook POST even if some steps failed — partial data is better than no data.
"""
