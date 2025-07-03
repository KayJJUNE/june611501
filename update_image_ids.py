import os
import re
import requests
import json
import sys

def update_image_ids():
    """
    Fetches image IDs from Cloudflare and updates the config.py file.
    """
    try:
        # --- 1. Get credentials from environment variables or user input ---
        CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")

        if not CLOUDFLARE_ACCOUNT_ID:
            CLOUDFLARE_ACCOUNT_ID = input("Enter your Cloudflare Account ID: ")
        if not CLOUDFLARE_API_TOKEN:
            CLOUDFLARE_API_TOKEN = input("Enter your Cloudflare API Token (needs Images:Read permission): ")

        # --- 2. Fetch all image data from Cloudflare ---
        print("Fetching image list from Cloudflare...")
        headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}

        images_list = []
        page = 1
        while True:
            url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/images/v1?page={page}&per_page=100"
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            if not data.get("success"):
                print("Error fetching images from Cloudflare:", file=sys.stderr)
                for error in data.get("errors", []):
                    print(f"- {error.get('message', 'Unknown error')}", file=sys.stderr)
                return

            images_list.extend(data['result']['images'])

            # If the number of images is less than per_page, it's the last page
            if len(data['result']['images']) < 100:
                break
            page += 1

        # --- 3. Create a mapping from filename to ID ---
        filename_to_id = {img['filename']: img['id'] for img in images_list}
        print(f"Found {len(filename_to_id)} images and created a mapping.")
        print(json.dumps(filename_to_id, indent=4))

        # --- 4. Read and update config.py ---
        config_path = 'config.py'
        if not os.path.exists(config_path):
            print(f"Error: {config_path} not found in the current directory.", file=sys.stderr)
            return

        print(f"Reading {config_path}...")
        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()

        CLOUDFLARE_IMAGE_BASE_URL = "https://imagedelivery.net/ZQ-g2Ke3i84UnMdCSDAkmw"
        # This pattern matches f-string URLs with either a filename (e.g., "kagari.png") 
        # or a Cloudflare ID (e.g., "6f52b492-b0eb-46d8-cd9e-0b5ec8c72800").
        pattern = re.compile(r'f"\{CLOUDFLARE_IMAGE_BASE_URL\}/([^/"]+)/public"')

        # Create a reverse map for efficient ID lookup
        id_to_filename = {v: k for k, v in filename_to_id.items()}

        def replace_url(match):
            identifier = match.group(1)
            original_url = match.group(0)

            # Case 1: Identifier is a full filename (e.g., 'kagari.png')
            if identifier in filename_to_id:
                new_id = filename_to_id[identifier]
                print(f"  - Replacing filename '{identifier}' with ID '{new_id}'")
                return f'f"{{CLOUDFLARE_IMAGE_BASE_URL}}/{new_id}/public"'

            # Case 2: Identifier is already a Cloudflare ID
            if identifier in id_to_filename:
                return original_url # It's a valid ID, no change needed

            # Case 3: Identifier is a filename base without an extension (e.g., 'kagari')
            for ext in ['.png', '.gif', '.jpg', '.jpeg']:
                potential_filename = f"{identifier}{ext}"
                if potential_filename in filename_to_id:
                    new_id = filename_to_id[potential_filename]
                    print(f"  - Matched base '{identifier}' to '{potential_filename}', replacing with ID '{new_id}'")
                    return f'f"{{CLOUDFLARE_IMAGE_BASE_URL}}/{new_id}/public"'

            # If none of the above, we can't resolve it (e.g., f-string variables like 'kagaric{i}')
            print(f"Warning: No Cloudflare ID found for identifier '{identifier}'. URL will not be changed.")
            return original_url

        updated_content, replacements_made = pattern.subn(replace_url, config_content)

        # We count actual changes, not just matches
        actual_replacements = 0
        if updated_content != config_content:
             # A simple way to count changes is to see if the content is different
             # For a more precise count, one would need to compare line by line or use a different method
             # This implementation will focus on whether an update happened or not.
             actual_replacements = 1 # Mark that at least one change was made.

        if actual_replacements > 0:
            print(f"Found matches and applied replacements.")
            # --- 5. Write the updated content back ---
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            print(f"Successfully updated {config_path}!")
        else:
            print("No matching image URLs were found to update. Please check the format in config.py.")

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)

if __name__ == "__main__":
    # Ensure the requests library is installed
    try:
        import requests
    except ImportError:
        print("The 'requests' library is not installed.", file=sys.stderr)
        print("Please install it by running: pip install requests", file=sys.stderr)
        sys.exit(1)

    update_image_ids() 