import requests
import json
import datetime

# The URL for LeetCode's public GraphQL API
LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"

# This is the GraphQL query we will send.
# It asks for the 'recentAcSubmissionList' for a given 'username' and 'limit'.
# We are requesting the problem's title, its unique 'titleSlug', and the 'timestamp'
# of when it was submitted.
RECENT_SUBMISSIONS_QUERY = """
query getRecentAcSubmissionList($username: String!, $limit: Int!) {
  recentAcSubmissionList(username: $username, limit: $limit) {
    id
    title
    titleSlug
    timestamp
  }
}
"""
# This query gets details for a *single* problem, specified by its "titleSlug".
QUESTION_DIFFICULTY_QUERY = """
query questionData($titleSlug: String!) {
  question(titleSlug: $titleSlug) {
    difficulty
    title
  }
}
"""

def fetch_recent_submissions(username: str, limit: int = 20):
    """
    Fetches the most recent 'limit' accepted submissions for a LeetCode user.

    Args:
        username: The LeetCode username.
        limit: The number of recent submissions to fetch.

    Returns:
        A list of submission dictionaries, or None if the request fails
        or the user is not found.
    """
    print(f"Attempting to fetch submissions for: {username}...")

    # This is the payload that will be sent as JSON in the POST request.
    # It specifies the query to run and the variables (username, limit)
    # that the query needs.
    json_payload = {
        "query": RECENT_SUBMISSIONS_QUERY,
        "variables": {
            "username": username,
            "limit": limit
        }
    }

    try:
        # We use a session for connection pooling and to set common headers
        with requests.Session() as s:
            # LeetCode's API may check for a user-agent and referer
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36",
                "Referer": f"https://leetcode.com/{username}/"
            })

            response = s.post(LEETCODE_GRAPHQL_URL, json=json_payload)

            # Check if the request was successful
            if response.status_code == 200:
                data = response.json()

                # Check for errors in the GraphQL response itself
                if "errors" in data:
                    print(f"Error in GraphQL response for {username}: {data['errors']}")
                    return None

                # Navigate to the data we want
                submissions = data.get("data", {}).get("recentAcSubmissionList")

                if submissions is None:
                    # This can happen if the user doesn't exist or has no submissions
                    print(f"No submission data found for user: {username}")
                    return []

                print(f"Successfully fetched {len(submissions)} submissions for {username}.")
                return submissions
            else:
                print(f"Failed to fetch data. Status code: {response.status_code}")
                print(f"Response: {response.text}")
                return None

    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the request: {e}")
        return None

# --- Example Usage ---

if __name__ == "__main__":
    # NOTE: Replace 'your_test_username' with a real LeetCode username
    # For example, a popular user like "neal_wu"
    TEST_USERNAME = "neal_wu"

    submissions = fetch_recent_submissions(TEST_USERNAME, limit=5)

    if submissions:
        print(f"\n--- Recent Submissions for {TEST_USERNAME} ---")
        for sub in submissions:
            # Timestamp is a string, convert it to an integer
            timestamp = int(sub['timestamp'])
            # Convert Unix timestamp to a readable datetime object
            submit_time = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)

            print(f"  Problem: {sub['title']} ({sub['titleSlug']})")
            print(f"  Time:    {submit_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")

    elif submissions == []:
        print(f"User {TEST_USERNAME} has no accepted submissions.")
    else:
        print(f"Could not retrieve submissions for {TEST_USERNAME}.")


def fetch_problem_difficulty(title_slug: str):
    """
    Бир маселенин кыйынчылыгын (Easy, Medium, Hard) жана аталышын (title) тартат.

    Args:
        title_slug: Маселенин уникалдуу URL дареги (мис., "two-sum").

    Returns:
        ("Easy", "Two Sum") сыяктуу (difficulty, title) кортежи
        же (None, None) (эгер ката кетсе).
    """
    json_payload = {
        "query": QUESTION_DIFFICULTY_QUERY,
        "variables": {
            "titleSlug": title_slug
        }
    }

    try:
        with requests.Session() as s:
            # ... (headers ошол бойдон калат) ...
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36",
                "Referer": f"https://leetcode.com/problems/{title_slug}/"
            })

            response = s.post(LEETCODE_GRAPHQL_URL, json=json_payload)

            if response.status_code == 200:
                data = response.json()

                if "errors" in data:
                    print(f"Error in GraphQL response for {title_slug}: {data['errors']}")
                    return (None, None)

                question_data = data.get("data", {}).get("question")

                if question_data:
                    difficulty = question_data.get("difficulty")
                    title = question_data.get("title")
                    if difficulty and title:
                        return (difficulty, title)

                print(f"No difficulty/title data found for slug: {title_slug}")
                return (None, None)
            else:
                return (None, None)

    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the request for difficulty: {e}")
        return (None, None)