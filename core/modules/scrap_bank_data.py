import requests
from bs4 import BeautifulSoup
import requests
from bs4 import BeautifulSoup
import re

class BankInformation:
    # Function to scrape bank branch info
    def scrape_branch_info(self,url):
        # Send a GET request to the URL
        response = requests.get(url)
        # Parse the HTML content
        soup = BeautifulSoup(response.content, 'html.parser')
        # Find the article containing branch info
        article = soup.find('article')    
        # Find the table containing branch names and codes
        table = article.find('table')
        # Initialize a list to store branch info
        branch_info = []
        # Loop through each row in the table
        for row in table.find_all('tr'):
            # Extract text from the row
            row_text = list(str(data.text).lower().strip() for data in row.find_all('td')[:2])
            # Use regex to find branch code and branch name
            header_keys=['branch name','branch code','branch code-name']
            if (row_text[0] or row_text[1]) not in header_keys:
                row_str=row_text[0]+" "+row_text[1]
                print(row_str)
                branch_code = re.search(r'\b\d+\b', row_str).group() if row_str else 'None'
                branch_name = re.search(r'\b\w+[a-zA-Z\s+(a-zA-Z)]+', row_str).group().strip() if row_str else 'None'
                bank_code = ''
                for p in article.find_all('p'):
                    if "Bank Code:" in p.text:
                        bank_code = p.text.strip()
                        bank_code=bank_code.split(':')[1].strip()
                        break            
                branch_info.append({'branch_name': branch_name, 'short_code':str(bank_code)+str(branch_code)})
        # Return bank name and branch info
        return branch_info

    def scrape_bank_info(self,url):
        # Send a GET request to the URL
        response = requests.get(url)
        # Check if the request was successful
        if response.status_code == 200:
            # Parse the HTML content
            soup = BeautifulSoup(response.content, 'html.parser')
            # Find the section containing the list of banks
            section = soup.find('div', id='main-content').find('div', class_='site-content')
            # Find the list of banks within the section
            bank_list = section.find('ol')
            # Initialize dictionaries to store bank names and their respective branch info links
            bank_info = {}
            bank_branches=[]
            # Iterate over each bank in the list
            for bank in bank_list.find_all('a'):
                bank_name = bank.text.strip()
                branch_info_link = bank['href']
                branch_data=self.scrape_branch_info(branch_info_link)
                for data in branch_data:
                    bank_branches.append(data)
                bank_info.update({'bank_name':bank_name,'branches':bank_branches})
                print(bank_info)
                bank_branches=[]#reset list
            # Return the dictionary containing bank names and their branch info links
            return bank_info
        else:
            print("Failed to retrieve data. Status code:", response.status_code)
            return None

bankInfo=BankInformation()
# URL of the website to scrape
url = "https://www.snowdesert.co.ke/resources/"
# Call the function to scrape data
bank_info =bankInfo.scrape_bank_info(url)

# Print the scraped data
if bank_info:
    for bank_name, branch_info in bank_info.items():
        print("Bank Name:", bank_name)
        print("Branch Info:", branch_info)
        print("-----------------------------")
else:
    print("Scraping failed. Please check the URL and try again.")
