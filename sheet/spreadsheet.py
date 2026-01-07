import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
load_dotenv()

import sys, os

C = os.path.abspath(os.path.dirname(__file__))


# use creds to create a client to interact with the Google Drive API
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/spreadsheets',
         'https://www.googleapis.com/auth/drive']


credentials = {
  "type": "service_account",
  "project_id": "operation-300",
  "private_key_id": "909975fa4d7e452f97f51c2fde66514d54476d78",
  "client_email": "paulxuan@operation-300.iam.gserviceaccount.com",
  "client_id": "105205709115878599213",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/paulxuan%40operation-300.iam.gserviceaccount.com"
}

credentials["private_key"] = os.getenv('GOOGLE_SHEET_PRIVATE_KEY')
# creds = ServiceAccountCredentials.from_json_keyfile_name(os.path.join(C, 'credentials.json'), scope)
creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials, scope)
client = gspread.authorize(creds)

# Find a workbook by name and open the first sheet
# Make sure you use the right name here.
# sheet = client.open("LISTE_CIRCO_1_3_5").sheet1

# Extract and print all of the values
# list_of_hashes = sheet.get_all_values()
# print(list_of_hashes)