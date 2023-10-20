# configs.py
import os
import requests
from logging import Logger, getLogger


import keys
REST_API_URL = keys.REST_API_URL
REST_API_TOKEN = keys.REST_API_TOKEN
TELEGRAM_API_TOKEN = keys.TELEGRAM_API_TOKEN
REDMINE_URL = keys.REDMINE_URL
REDMINE_API_KEY = keys.REDMINE_API_KEY
REDMINE_API_KEY_admin = keys.REDMINE_API_KEY_admin
ADMIN_TELEGRAM_ID =  keys.ADMIN_TELEGRAM_ID


# REST_API_URL = os.environ["REST_API_URL"]
# REST_API_TOKEN = os.environ["REST_API_TOKEN"]
# TELEGRAM_API_TOKEN = os.environ["TELEGRAM_API_TOKEN"]
# REDMINE_URL = os.environ["REDMINE_URL"]
# REDMINE_API_KEY = os.environ["REDMINE_API_KEY"]
# REDMINE_API_KEY_admin = os.environ["REDMINE_API_KEY_admin"]
# ADMIN_TELEGRAM_ID =  os.environ["ADMIN_TELEGRAM_ID"]



ALLOWED_TELEGRAM_IDS = [ADMIN_TELEGRAM_ID]  # update this list as required





class ServerError(Exception):
    def __str__(self):
        return "Server error (response.status_code not in (200, 201, 204))"


class NoTidError(Exception):
    def __init__(self, tid):
        self.tid = tid

    def __str__(self):
        return f"User tid={self.tid} has no access"


class User:
    def __init__(self, telegram_id: str="",
                 uid: str="",
                 roles_target_id: str="",
                 name: str = None,
                 second_name: str = None,
                 **kwargs):
        self.user_id = str(telegram_id)
        self.uid = str(uid)
        self.roles = [r for r in roles_target_id.split(',')]
        self.name = name
        self.second_name = second_name
        self.__dict__.update(kwargs)

    def __repr__(self):
        return str(self.__dict__)


class BadRoleError(Exception):
    def __init__(self, user: User):
        self.tid = user.user_id
        self.roles = user.roles
        self.uid = user.uid

    def __str__(self):
        return f"User tid={self.tid}, uid={self.uid}, roles=[{', '.join(self.roles)}] has no access due to role"


class UserAPI:
    def __init__(self, token: str, logger: Logger = None, timeout=10):
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        self.logger = getLogger() if logger is None else logger
        self.test = False

    def request(self, url: str, params: list) -> dict or None or list:
        headers = {
            "Authorization": f"Bearer {self.token}"
        }

        response = self.session.request('GET', url,
                                        params=params,
                                        headers=headers,
                                        timeout=self.timeout)
        if response.status_code not in (200, 201, 204):  
            self.logger.error(response.text)
            raise ServerError
        return response.json()

    def get_user_by_tid(self, user_tid: int) -> User or None:
        url = "https://physics.itmo.ru/ru/rest/export/json/check-users-roles-email"
    
        params = [
            ("_format", "json"),
            ("telegram_id_value", user_tid)
        ]
    
        response = self.request(url, params)
    
        if not response: 
            return None

        u = self.request(url=url, params=params)  
        #mail = getting_redmine_user_data(u[0]['mail'])
        mail = u[0]['mail']
        print(u[0]['mail'])
        #print (user)
        if len(u) == 0:
            raise NoTidError(user_tid)

        user = User(**u[0])

        if 'member' not in user.roles:
            raise BadRoleError(user)

        response = requests.get(
        'https://helpdesk.physics.itmo.ru/users.json?name=' + str(mail) + '&key=' + str(REDMINE_API_KEY_admin))
        data = response.json()
        redmine_id = data['users'][0]['id']
        # Getting redmine user API
        response_api = requests.get(
            'https://helpdesk.physics.itmo.ru/users/' + str(redmine_id) + '.json?key=' + str(REDMINE_API_KEY_admin))
        data_api = response_api.json()
        redmine_user_api = data_api['user']['api_key']



        return user, mail,redmine_user_api

# def get_user_by_tid(self, user_tid: int) -> User or None:
#     url = "https://physics.itmo.ru/ru/rest/export/json/check-users-roles-email"
    
#     params = [
#         ("_format", "json"),
#         ("telegram_id_value", user_tid)
#     ]
    
#     response = self.request(url, params)
    
#     if not response: 
#         return None

#     u = self.request(url=url, params=params)  

#     if len(u) == 0:
#         raise NoTidError(user_tid)

#     user = User(**u[0])

#     if 'member' not in user.roles:
#         raise BadRoleError(user)

#     return user


# async def getting_redmine_user_data(mail):
#     response = requests.get(
#         'https://helpdesk.physics.itmo.ru/users.json?name=' + str(mail) + '&key=' + str(REDMINE_API_KEY_admin))
#     data = response.json()
#     redmine_id = data['users'][0]['id']
#     # Getting redmine user API
#     response_api = requests.get(
#         'https://helpdesk.physics.itmo.ru/users/' + str(redmine_id) + '.json?key=' + str(REDMINE_API_KEY_admin))
#     data_api = response_api.json()
#     redmine_user_api = data_api['user']['api_key']
#     return redmine_user_api    
