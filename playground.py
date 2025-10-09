import requests
from bs4 import BeautifulSoup

def decode_secret_message(url):
    # Fetch the document content
    response = requests.get(url)
    
    if response.status_code != 200:
        print("Error: Unable to fetch the document.")
        return
    
    # Get the content of the document (as HTML)
    content = response.text
    
    # Parse the HTML content with BeautifulSoup
    soup = BeautifulSoup(content, 'html.parser')
    
    # Extract the content as plain text
    paragraphs = soup.find_all('p')
    
    # Extract text from the paragraphs that represent coordinates and characters
    text_content = [text.get_text().strip() for text in paragraphs if len(text.get_text().strip()) in [1,2]]  # Only keep relevant data, ignore the intro paragraph
    print(text_content)
    # Filter to make sure we have a valid number of items (groups of 3)
    if len(text_content) % 3 != 0:
        print("Error: The data format seems incorrect.")
        return
    
    # Dictionary to store grid positions
    grid_data = {}
    
    # Initialize min and max values for coordinates
    min_x, min_y, max_x, max_y = None, None, None, None
    
    # Process the content in groups of 3 (x-coordinate, character, y-coordinate)
    for i in range(0, len(text_content), 3):
        if i + 2 >= len(text_content):  # Ensure there are enough lines, at least 3
            break
        
        x = int(text_content[i].strip())  # x-coordinate
        char = text_content[i + 1].strip()  # character
        y = int(text_content[i + 2].strip())  # y-coordinate
        
        # Store the character at the (x, y) position
        grid_data[(x, y)] = char
        
        # Update the min/max coordinates
        if min_x is None or x < min_x:
            min_x = x
        if min_y is None or y < min_y:
            min_y = y
        if max_x is None or x > max_x:
            max_x = x
        if max_y is None or y > max_y:
            max_y = y
    
    # Check if any valid data was found
    if min_x is None or min_y is None or max_x is None or max_y is None:
        print("Error: No valid grid data found in the document.")
        return
    
    # Create the grid (initialize with spaces)
    grid = []
    for y in range(min_y, max_y + 1):
        row = []
        for x in range(min_x, max_x + 1):
            row.append(grid_data.get((x, y), ' '))  # Fill missing positions with spaces
        grid.append(''.join(row))
    
    # Print the grid
    for row in grid:
        print(row)

# Example usage:
url = "https://docs.google.com/document/d/e/2PACX-1vRMx5YQlZNa3ra8dYYxmv-QIQ3YJe8tbI3kqcuC7lQiZm-CSEznKfN_HYNSpoXcZIV3Y_O3YoUB1ecq/pub"
decode_secret_message(url)
