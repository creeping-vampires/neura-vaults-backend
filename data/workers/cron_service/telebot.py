import os
import asyncio
import logging
import httpx  
from dotenv import load_dotenv

# --- Configuration & Logging ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BASE_URL = os.getenv("TELEGRAM_BASE_URL")

CONCURRENCY_LIMIT = 25 
MAX_RETRIES = 5 
INITIAL_BACKOFF_DELAY = 1 

MAX_RETRIES = 5  # Try a total of 5 times
INITIAL_BACKOFF_DELAY = 1  # Start with a 1-second wait
'''
async def get_all_user_ids_from_api() -> list[int]:
    """Fetches all user chat_ids from the FastAPI backend."""
    if not API_BASE_URL:
        logger.error("API_BASE_URL not set in .env file.")
        return []
        
    url = f"{API_BASE_URL}/users/ids/"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Failed to get users from API. Status: {response.status_code}, Response: {response.text}")
                return []
    except httpx.RequestError as e:
        logger.error(f"Error connecting to API to get users: {e}")
        return []
'''
async def get_all_user_ids_from_api() -> list[int]:
    """
    Fetches all user chat_ids from the FastAPI backend with a robust retry mechanism.
    """
    if not API_BASE_URL:
        logger.error("API_BASE_URL not set in .env file.")
        return []

    url = f"{API_BASE_URL}/users/ids/"
    delay = INITIAL_BACKOFF_DELAY

    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10)
                if response.status_code == 200:
                    return response.json()  # Success! Exit the function.
                else:
                    # This is a server error, not a network error. Retrying might not help, but we'll try anyway.
                    logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: API returned non-200 status: {response.status_code}")

        except httpx.RequestError as e:
            # This is the exact type of error you are seeing ([Errno 11001]).
            logger.warning(f"Attempt {attempt + 1}/{MAX_RETRIES}: Network error connecting to API: {e}")

        # If we've reached this point, the attempt failed. Wait before the next one.
        if attempt < MAX_RETRIES - 1:
            logger.info(f"Waiting {delay} seconds before retrying...")
            await asyncio.sleep(delay)
            delay *= 2  # Double the delay for the next attempt (exponential backoff)

    # If the loop finishes without a successful return, all retries have failed.
    logger.critical(f"FATAL: Could not get user list from API after {MAX_RETRIES} attempts.")
    return []



async def remove_user_via_api(chat_id: int):
    """Tells the FastAPI backend to remove a user."""
    if not API_BASE_URL:
        return
        
    url = f"{API_BASE_URL}/users/{chat_id}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(url, timeout=10)
            if response.status_code == 204:
                logger.warning(f"Removed user {chat_id} from the database via API.")
            else:
                logger.info(f"API attempt to remove user {chat_id} failed. Status: {response.status_code}")
    except httpx.RequestError as e:
        logger.error(f"Error connecting to API to remove user: {e}")


# --- Asynchronous Broadcasting Logic ---
'''
async def send_telegram_message(session: httpx.AsyncClient, chat_id: int, message: str) -> bool:
    """Sends a message to a specific chat_id using an httpx session."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    
    try:
        response = await session.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            return True
        elif response.status_code == 403: # User blocked the bot
            # UPDATED: Call the new API function to remove the user
            await remove_user_via_api(chat_id)
            return False
        else:
            logger.error(f"Failed to send to {chat_id}: Status {response.status_code}, Response: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Exception while sending to {chat_id}: {e}")
        return False'''


async def send_telegram_message(session: httpx.AsyncClient, chat_id: int, message: str) -> bool:
    """
    Sends a message to a specific chat_id, with retry logic for rate limiting.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    
    for attempt in range(MAX_RETRIES):
        try:
            response = await session.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                return True # Message sent successfully
                
            elif response.status_code == 429: # Rate limit exceeded
                # Telegram often provides a 'retry_after' value in the response
                retry_after = response.json().get("parameters", {}).get("retry_after", 0)
                
                # If Telegram tells us how long to wait, we listen.
                if retry_after > 0:
                    wait_time = retry_after
                    logger.warning(f"Rate limit hit. Waiting {wait_time}s as requested by Telegram API.")
                else:
                    # Otherwise, use exponential backoff
                    wait_time = INITIAL_BACKOFF_DELAY * (2 ** attempt)
                    logger.warning(f"Rate limit hit. Applying exponential backoff, waiting {wait_time}s.")
                
                await asyncio.sleep(wait_time)
                continue # Go to the next attempt

            elif response.status_code == 403: # User blocked the bot
                logger.warning(f"User {chat_id} has blocked the bot. Removing from database.")
                await remove_user_via_api(chat_id)
                return False # Failed, but handled
                
            else:
                logger.error(f"Failed to send to {chat_id}: Status {response.status_code}, Response: {response.text}")
                return False # Unrecoverable error for this user

        except httpx.RequestError as e:
            logger.error(f"HTTP Request error for {chat_id}: {e}")
            return False # Network-related error
        except Exception as e:
            logger.error(f"An unexpected exception occurred for {chat_id}: {e}")
            return False # Other unexpected errors

    logger.error(f"Failed to send message to {chat_id} after {MAX_RETRIES} attempts.")
    return False
'''
async def broadcast_messages(message: str):
    """Fetches all user IDs from the API and sends them a message concurrently."""
    # UPDATED: Call the new API function to get user IDs
    user_ids = await get_all_user_ids_from_api()
    if not user_ids:
        logger.info("No users found via API to broadcast to.")
        return

    logger.info(f"Broadcasting message to {len(user_ids)} user(s)...")

    async with httpx.AsyncClient() as session:
        tasks = [send_telegram_message(session, chat_id, message) for chat_id in user_ids]
        results = await asyncio.gather(*tasks)

    success_count = sum(1 for res in results if res)
    logger.info(f"Broadcast complete. Message sent to {success_count}/{len(user_ids)} users.")'''

async def broadcast_messages(user_ids: list[int],message: str):
    """
    Fetches all user IDs and sends them a message concurrently, respecting rate limits.
    """
    logger.info(f"Starting broadcast to {len(user_ids)} user(s)...")

    semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def send_with_semaphore(session: httpx.AsyncClient, chat_id: int, msg: str):
        """Wrapper to acquire semaphore before sending the message."""
        async with semaphore:
            return await send_telegram_message(session, chat_id, msg)

    async with httpx.AsyncClient() as session:
        tasks = [send_with_semaphore(session, chat_id, message) for chat_id in user_ids]
        results = await asyncio.gather(*tasks)

    success_count = sum(1 for res in results if res)
    logger.info(f"Broadcast complete. Message sent to {success_count}/{len(user_ids)} users.")


# --- Example Usage ---
async def main():
    """Main function to run the broadcast."""
    if not TELEGRAM_TOKEN or not API_BASE_URL:
        logger.critical("FATAL ERROR: TELEGRAM_BOT_TOKEN or API_BASE_URL not found in .env file.")
        return
        
    # Make sure your FastAPI server is running before you execute this script!
    logger.info("Starting broadcast...")
    example_message = "This is a test broadcast from the new system! 🚀"
    await broadcast_messages(example_message)
    logger.info("Broadcast finished.")

if __name__ == "__main__":
    asyncio.run(main())