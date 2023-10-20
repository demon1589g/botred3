

#rrr.py
import requests
import logging
import re
import configs
import asyncio
from itertools import islice
import math
import time
from redminelib import Redmine, exceptions
from redminelib.exceptions import ResourceNotFoundError
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text, Command, Regexp
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor, exceptions as aiogram_exceptions
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from configs import REST_API_TOKEN, User, TELEGRAM_API_TOKEN, REDMINE_URL, REST_API_URL, ADMIN_TELEGRAM_ID, ALLOWED_TELEGRAM_IDS, REDMINE_API_KEY_admin
from datetime import datetime, timedelta
import aioschedule as schedule


ITEMS_PER_PAGE = 8
PAGE_SIZE = 10

USER_API = configs.UserAPI(REST_API_TOKEN)
bot = Bot(token=TELEGRAM_API_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
notifications_started = False
user_notifications = {}
user_notifications_status = {}
issue_creation_steps = ['Проект', 'Тема', 'Описание', 'Исполнитель', 'Приоритет', 'Дата завершения']
user_issue_creation = {}
last_bot_messages = {}


EMAIL = ""

async def get_redmine_async(user_id):
    api_key = get_redmine_api.get_token(user_id)
    if api_key is None:
        raise ValueError("Пользователь не найден.")
    return RedmineAPI(get_redmine_api.url(user_id), api_key)

async def get_redmine(user_id) -> Redmine:
    if user_id not in user_redmines:
        user, mail, redmine_api_key  = USER_API.get_user_by_tid(user_id)
        user_redmines[user_id] = RedmineAPI(REDMINE_URL, redmine_api_key)
    return user_redmines[user_id]




class RedmineAPI:
    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token
        self.redmine = Redmine(url, key=token)


def get_redmine_api(user_id):
    user, mail,redmine_api_key  = USER_API.get_user_by_tid(user_id)
    REDMINE_API = RedmineAPI(url=REDMINE_URL, token=redmine_api_key)
    return REDMINE_API

#REDMINE_API = RedmineAPI(url=REDMINE_URL, token=get_redmine_api_key())

from configs import REDMINE_URL, REDMINE_API_KEY_admin

def get_redmine_api_admin(user_id):
    
    if user_id == ADMIN_TELEGRAM_ID:
      
        REDMINE_API_KEY = REDMINE_API_KEY_admin
    else:
       
        REDMINE_API_KEY = REDMINE_API_KEY

    REDMINE_API = RedmineAPI(url=REDMINE_URL, token=REDMINE_API_KEY)
    return REDMINE_API



async def get_user(redmine, user_id):
    cache_key = f"user_{user_id}"
    cached_user = get_from_cache(cache_key)
    if cached_user is not None:
        return cached_user
    user = redmine.redmine.user.get(user_id, include='groups')
    update_cache(cache_key, user)
    return user



async def create_issue(redmine, project_id, subject, description, assigned_to_id, priority_id, due_date, watcher_user_ids=None):
    logger.info(f"Create issue - project_id: {project_id}, subject: {subject}, description: {description}, assigned_to_id: {assigned_to_id}, priority_id: {priority_id}, due_date: {due_date}, watcher_user_ids: {watcher_user_ids}")
    if not priority_id:
        raise ValueError("Пожалуйста, выберите приоритет задачи.")

    issue = redmine.redmine.issue.create(
        project_id=project_id,
        subject=subject,
        description=description,
        assigned_to_id=assigned_to_id,
        priority_id=priority_id,
        due_date=due_date,
        watcher_user_ids=watcher_user_ids
    )
    return issue



@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    logger.info(f"Start - user_id: {message.from_user.id}")
    user_id = message.from_user.id
    try:
        user = USER_API.get_user_by_tid(user_id)
        if user is not None:
            # user_notifications_status[user_id] = True 
            markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
            markup.add(KeyboardButton("Просмотр задач 👁️"))
            #markup.add(KeyboardButton("Начало"))
            markup.add(KeyboardButton("Создать задачу 🛠️"))
            markup.add(KeyboardButton("Включить/Выключить уведомления 🔔"))


            # global notifications_started
            # if not notifications_started:
            #     # Если это первый раз, когда пользователь включает уведомления, запускаем сразу же проверку обновлений
            #     notifications_started = True
            #     await check_updates(user_id)  # Сразу проверяем обновления
            
            if str(user_id) in configs.ADMIN_TELEGRAM_ID:
                markup.add(KeyboardButton("Админская кнопка 👹"))
            
            await bot.send_message(message.chat.id, "Выберите действие:", reply_markup=markup)
        else:
            await bot.send_message(message.chat.id, "Telegram ID не найден в базе. У вас нет доступа к этому боту.")
    except Exception as e:
        await bot.send_message(
            message.chat.id, "Произошла ошибка при попытке получения информации о пользователе. Пожалуйста, попробуйте снова позже.")
        logger.error(f"An error occurred while trying to fetch user: {e}")

chosen_projects = {}


async def periodic_check_projects():
    while True:
        for user_id, projects in chosen_projects.items():
            await check_and_update_issues(user_id, projects, inactivity_period_days=14)
        await asyncio.sleep(12 * 60 * 60)  # Пауза на 12 часов

# Запуск асинхронной задачи



async def get_projects_with_tasks_admin():
    logger.info("Get projects with tasks")
    redmine = get_redmine_api_admin(ADMIN_TELEGRAM_ID)  
    all_projects = redmine.redmine.project.all()
    projects_with_tasks = {}

    for project in all_projects:
        issues = redmine.redmine.issue.filter(project_id=project.id, status_id="*")  
        if issues:
            projects_with_tasks[project.id] = issues

    return projects_with_tasks

async def generate_markup_for_projects(user_id):
    markup = types.InlineKeyboardMarkup()

    projects = await get_projects_with_tasks_admin()
    user_chosen_projects = chosen_projects.get(user_id, {})

    chosen_projects_indicator = "🟢"  # Индикатор, что проект был выбран

    for project_id, issues in projects.items():
        project_name = issues[0].project.name if issues else "Неизвестный проект"
        text = f"{project_name} {chosen_projects_indicator if project_id in user_chosen_projects else ''}"
        btn = types.InlineKeyboardButton(text=text, callback_data=f"choose_project_{project_id}")
        markup.add(btn)

    btn_done = types.InlineKeyboardButton(text="Готово", callback_data="projects_done")
    markup.add(btn_done)

    return markup

@dp.message_handler(lambda message: message.text == "Админская кнопка 👹" and str(message.from_user.id) == ADMIN_TELEGRAM_ID)
async def admin_button_handler(message: types.Message):
    logger.info("Admin button handler was triggered")
    markup = await generate_markup_for_projects(message.from_user.id)
    await bot.send_message(message.chat.id, "Выберите проекты для проверки:", reply_markup=markup)











@dp.callback_query_handler(lambda c: c.data.startswith('choose_project_'))
async def process_callback_choose_project(callback_query: types.CallbackQuery):
    try:
        logger.debug("process_callback_choose_project triggered")
        user_id = callback_query.from_user.id
        project_id = int(callback_query.data.split("_")[2])  # Преобразуйте в int

        if user_id not in chosen_projects:
            chosen_projects[user_id] = {}

        if project_id in chosen_projects[user_id]:
            del chosen_projects[user_id][project_id]
            await bot.answer_callback_query(callback_query.id, f"Проект {project_id} удален из списка.")
        else:
            all_project_tasks = await get_projects_with_tasks_admin()
            chosen_projects[user_id][project_id] = all_project_tasks[project_id]
            await bot.answer_callback_query(callback_query.id, f"Проект {project_id} добавлен для проверки.")

        # Обновляем клавиатуру
        markup = await generate_markup_for_projects(user_id)
        await bot.edit_message_text("Выберите проекты для проверки:", callback_query.message.chat.id, callback_query.message.message_id, reply_markup=markup)

    except Exception as e:
        logger.error(f"Error in process_callback_choose_project: {e}", exc_info=True)





@dp.callback_query_handler(lambda c: c.data == 'projects_done')
async def process_callback_projects_done(callback_query: types.CallbackQuery):
    try:
        logger.info("process_callback_projects_done triggered")
        print("Entering process_callback_projects_done")
        user_id = callback_query.from_user.id

        if user_id in chosen_projects:
            await check_and_update_issues(user_id, chosen_projects[user_id])
            
        else:
            await bot.send_message(callback_query.from_user.id, "Вы не выбрали ни одного проекта.")
    except Exception as e:
        logger.error(f"Error in process_callback_projects_done: {e}")
        print("Entering process_callback_projects_done")

# async def check_and_update_issues(user_id, project_ids, inactivity_period_minutes=2):
async def check_and_update_issues(user_id, project_ids, inactivity_period_days=14):

    try:
        logger.info(f"Started check_and_update_issues for user {user_id} with projects {project_ids}")
        redmine = get_redmine_api_admin(ADMIN_TELEGRAM_ID)
        status_mapping = {
            'new': 1,
            'feedback': 4,
            'in progress': 2,
            'completed': 6,
            'verified': 7,
            'expired': 8,
            'stalled': 9
        }

        now = datetime.now()
        # inactivity_threshold = now - timedelta(minutes=inactivity_period_minutes)
        inactivity_threshold = now - timedelta(days=inactivity_period_days)

        all_issues = []

        for project_id in project_ids:
            issues = redmine.redmine.issue.filter(project_id=project_id, status_id=status_mapping["completed"])
            logger.debug(f"Found {len(issues)} issues with 'completed' status for project_id {project_id}")
            all_issues.extend(issues)

        for issue in all_issues:
            logger.debug(f"Processing issue with id: {issue.id}")

            if isinstance(issue.updated_on, datetime):
                updated_on = issue.updated_on
            else:
                try:
                    updated_on = datetime.strptime(issue.updated_on, "%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    logger.error(f"Failed to convert issue.updated_on to datetime. Type: {type(issue.updated_on)}, Value: {issue.updated_on}")
                    continue

            logger.debug(f"Comparing issue updated_on: {updated_on} with inactivity_threshold: {inactivity_threshold}")
            
            
            if issue.status.id == status_mapping["completed"] and updated_on <= inactivity_threshold:
                logger.debug(f"Trying to update status for issue with id: {issue.id}")
                
                try:
                    issue.status_id = status_mapping["verified"]
                    logger.debug(f"Set status for issue with id: {issue.id}")
                    
                    comment = "Статус задачи изменён на verified ботом автоматически."
                    issue.notes = comment
                    logger.debug(f"Set notes for issue with id: {issue.id}")
                    
                    issue.save()
                    logger.debug(f"Saved changes for issue with id: {issue.id}")
                except AttributeError as e:
                    logger.error(f"AttributeError while processing issue with id {issue.id}: {e}")


        await bot.send_message(user_id, "Проверка и обновление задач завершены.")
    except Exception as e:
        logger.error(f"Error in check_and_update_issues: {e}")











async def handle_create_issue(callback_query: types.CallbackQuery):
    logger.info(f"Create issue - user_id: {callback_query.from_user.id}")
    user_id = callback_query.from_user.id
    user_issue_creation[user_id] = {} 
    redmine =await get_redmine(user_id)

    logger.info(f"Fetching projects - user_id: {user_id}")
    projects = await get_projects(user_id)
    if not projects: 
        await bot.send_message(user_id, 'Нет доступных проектов.')
        return
    kb = InlineKeyboardMarkup()
    for project in projects:
        kb.add(InlineKeyboardButton(project.name, callback_data=f'project_{project.id}'))
    await bot.send_message(user_id, 'Выберите проект:', reply_markup=kb)
    user_issue_creation[user_id] = {'stage': 'project'}
    logger.info(f"Projects fetched - user_id: {user_id}")


def cancel_button_creation():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Отмена ввода", callback_data="cancel_issue_creation"))
    return markup

@dp.callback_query_handler(lambda c: c.data.startswith('project_'))
async def process_callback_project(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"Project callback - user_id: {user_id}")
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'project':
        return
    project_id = int(callback_query.data.split('_')[1])
    user_data['project'] = project_id
    user_data['stage'] = 'subject'
    await bot.send_message(user_id, 'Введите тему задачи:', reply_markup=cancel_button_creation())


@dp.message_handler(lambda message: user_issue_creation.get(message.from_user.id, {}).get('stage') == 'subject')
async def process_message_subject(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"Subject input - user_id: {user_id}")
    user_data = user_issue_creation.get(user_id)
    user_data['subject'] = message.text
    user_data['stage'] = 'description'
    await bot.send_message(user_id, 'Введите описание задачи:', reply_markup=cancel_button_creation())

@dp.callback_query_handler(lambda c: c.data == 'cancel_issue_creation')
async def handle_cancel_issue_creation(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is not None:
        user_data['stage'] = None  # или удалите 'stage' из user_data
    await bot.answer_callback_query(callback_query.id, "Создание задачи отменено")
    await bot.send_message(user_id, "Создание задачи отменено.")


@dp.message_handler(lambda message: user_issue_creation.get(message.from_user.id, {}).get('stage') == 'description')
async def process_message_description(message: types.Message):
    user_id = message.from_user.id
    logger.info(f"Description input - user_id: {user_id}")
    user_data = user_issue_creation.get(user_id)
    user_data['description'] = message.text
    user_data['stage'] = 'assignee'
    await process_message_assignee(message)

@dp.callback_query_handler(lambda c: c.data.startswith('user_'))
async def process_callback_user(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"User callback - user_id: {user_id}")
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'get_assignee':
        return
    assignee_id = int(callback_query.data.split('_')[1])
    user_data['assignee'] = assignee_id
    logger.info(f"Assignee selected - user_id: {user_id}, assignee_id: {assignee_id}")

    redmine =await get_redmine(user_id)
    project_id = user_data['project']
    project = redmine.redmine.project.get(project_id)

    users = []
    groups = []

    for membership in project.memberships:
        if hasattr(membership, 'user') and membership.user:
            user = membership.user
            users.append(user)
        elif hasattr(membership, 'group') and membership.group:
            group = membership.group
            groups.append(group)

    user_data['users'] = users
    user_data['groups'] = groups
    user_data['stage'] = 'priority'
    user_issue_creation[user_id] = user_data

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton('Low', callback_data='priority_low'))
    kb.add(InlineKeyboardButton('Normal', callback_data='priority_normal'))
    kb.add(InlineKeyboardButton('High', callback_data='priority_high'))
    kb.add(InlineKeyboardButton('Urgent', callback_data='priority_urgent'))
    kb.add(InlineKeyboardButton('Immediate', callback_data='priority_immediate'))
    await bot.send_message(user_id, 'Выберите приоритет задачи:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('priority_'))
async def process_callback_priority_issue(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'priority':
        return
    priority_mapping = {
        'low': 1,
        'normal': 2,
        'high': 3,
        'urgent': 4,
        'immediate': 5
    }
    priority = callback_query.data.split('_')[1]
    priority_value = priority_mapping.get(priority.lower())
    priority_name = list(priority_mapping.keys())[list(priority_mapping.values()).index(priority_value)]
    if priority_value is None:
        await bot.answer_callback_query(callback_query.id, text='Неверное значение приоритета.')
        return
    user_data['priority'] = priority_value
    user_data['priorityname'] = priority_name  
    logger.info(f"Priority set - user_id: {user_id}, priority: {priority}")
    user_data['stage'] = 'due_date'
    user_issue_creation[user_id] = user_data
    
    await bot.send_message(user_id, 'Введите дату завершения задачи в формате ДД.ММ.ГГГГ или ДД ММ ГГГГ :', reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton('Пропустить', callback_data='skip_due_date')))

def get_list_assingee_users(project):
    users = []
    for membership in project.memberships:
        if hasattr(membership, 'user') and membership.user:
            user = membership.user
            name = user.name
            user_id = user.id
            users.append((name, user_id))
        elif hasattr(membership, 'group') and membership.group:
            group = membership.group
            name = group.name
            group_id = group.id
            users.append((name, group_id))
    return users




async def process_message_assignee(message: types.Message, page: int = 1, project_id: int = None):
    bot_user_id = message.from_user.id
    logger.info(f"Assignee step - bot_user_id: {bot_user_id}")

    user_data = user_issue_creation.get(bot_user_id, {'stage': 'get_assignee'})
    user_data['stage'] = 'get_assignee'

    if project_id is None:
       
        project_id = user_data.get('project')

    redmine = await get_redmine(bot_user_id)
    project = redmine.redmine.project.get(project_id)
    user_data['users'] = get_list_assingee_users(project)
    user_issue_creation[bot_user_id] = user_data  

    ITEMS_PER_PAGE = 5  
    total_pages = (len(get_list_assingee_users(project)) - 1) // ITEMS_PER_PAGE + 1

    start_index = (page - 1) * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    users_slice = get_list_assingee_users(project)[start_index:end_index]

    logger.info(f"Page: {page}, Start index: {start_index}, End index: {end_index}, Total users: {len(get_list_assingee_users(project))}")

    kb = InlineKeyboardMarkup(row_width=1)
    for user in users_slice:
        name, user_id = user
        kb.add(InlineKeyboardButton(name, callback_data=f'user_{user_id}'))
    if page > 1:
        kb.insert(InlineKeyboardButton('Previous', callback_data=f'previous_page:{page-1}:{project_id}'))
    if end_index < len(get_list_assingee_users(project)):
        kb.add(InlineKeyboardButton('Next', callback_data=f'next_page:{page+1}:{project_id}'))

    
    assignee_message = await bot.send_message(message.chat.id, 'Choose an assignee:', reply_markup=kb)
    user_data['assignee_message_id'] = assignee_message.message_id
    user_issue_creation[bot_user_id] = user_data

    
    await bot.delete_message(message.chat.id, message.message_id)


@dp.callback_query_handler(lambda c: c.data.startswith('next_page:'))
async def process_callback_next_page(callback_query: types.CallbackQuery):
    _, page, project_id = callback_query.data.split(':')
    page = int(page)
    await bot.answer_callback_query(callback_query.id)  
    await bot.edit_message_reply_markup(callback_query.message.chat.id, callback_query.message.message_id)  
    await process_message_assignee(callback_query.message, page, project_id)  


@dp.callback_query_handler(lambda c: c.data.startswith('previous_page:'))
async def process_callback_previous_page(callback_query: types.CallbackQuery):
    _, page, project_id = callback_query.data.split(':')
    page = int(page)
    await bot.answer_callback_query(callback_query.id)  
    await bot.edit_message_reply_markup(callback_query.message.chat.id, callback_query.message.message_id)  
    await process_message_assignee(callback_query.message, page, project_id)


def get_project_info(project_id, assigned, user_id):
    user, mail,redmine_api_key  = USER_API.get_user_by_tid(user_id)
    redmine = Redmine(REDMINE_URL, key=redmine_api_key)
    project_name = redmine.project.get(project_id)

    try:
        assignee = redmine.user.get(assigned)
        assignee_name = f"{assignee.firstname} {assignee.lastname}"
    except ResourceNotFoundError:
        assignee = redmine.group.get(assigned)
        assignee_name = assignee.name

    return project_name.name, assignee_name






@dp.message_handler(lambda message: user_issue_creation.get(message.from_user.id, {}).get('stage') == 'due_date')
async def set_due_date(message: types.Message):
    user_id = message.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'due_date':
        return
    
    due_date_str = message.text
    
    # Определите все форматы, которые вы хотите поддерживать
    date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d %m %Y"]
    due_date = None
    
    for fmt in date_formats:
        try:
            due_date = datetime.strptime(due_date_str, fmt).date()
            break  # Выход из цикла, если парсинг удался
        except ValueError:
            pass  # Продолжаем цикл, если парсинг не удался
    
    if due_date is None:
        await bot.send_message(
            message.chat.id, 
            'Неверный формат даты. Пожалуйста, введите дату в одном из форматов:ДД.ММ.ГГГГ или ДД ММ ГГГГ, или выберите Пропустить.', 
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton('Пропустить', callback_data='skip_due_date'))
        )
        return
    
    # Проверка, что выбранная дата не раньше текущей
    if due_date < datetime.now().date():
        await bot.send_message(
            message.chat.id,
            'Дата не может быть раньше текущей. Пожалуйста, введите корректную дату или выберите Пропустить.',
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton('Пропустить', callback_data='skip_due_date'))
        )
        return
    
    user_data['due_date'] = due_date
    logger.info(f"Due date set - user_id: {user_id}, due_date: {due_date}")
    user_data['stage'] = 'confirm'
    await confirm_issue(user_id)


# Обработчик, который срабатывает, когда пользователь вводит неверный формат даты.
@dp.message_handler(lambda message: user_issue_creation.get(message.from_user.id, {}).get('stage') == 'due_date')
async def set_due_date_invalid(message: types.Message):
    await bot.send_message(message.chat.id, 'Формат даты неверен. Пожалуйста, введите дату в формате ДД.ММ.ГГГГ или ДД ММ ГГГГ или выберите Пропустить.',reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton('Пропустить', callback_data='skip_due_date')))

# Обработчик, который срабатывает, когда пользователь пропускает установку даты.
@dp.callback_query_handler(lambda c: c.data == 'skip_due_date')
async def process_callback_skip_due_date(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'due_date':
        logger.error(f"Error on skipping due date - user_id: {user_id}, stage: {user_data.get('stage', 'None') if user_data else 'No user_data'}")
        return
    
    user_data['due_date'] = None
    user_data['stage'] = 'confirm'
    await bot.send_message(user_id, text='Дата завершения пропущена.')
    await confirm_issue(user_id)

async def confirm_issue(user_id: int):
    user_data = user_issue_creation.get(user_id)
    if user_data is None:
        logger.error(f"Error on confirming issue - user_id: {user_id}, No user_data")
        await bot.send_message(user_id, "Произошла ошибка, пожалуйста, начните процесс создания задачи сначала.")
        return
    project_id = user_data['project']
    assignee_id = user_data['assignee']
    priority_name = user_data['priorityname']
    try:
        project_name, assignee_name = get_project_info(project_id, assignee_id,user_id)
    except Exception as e:
        logger.error(f"Error on getting project info - project_id: {project_id}, assignee_id: {assignee_id}, error: {str(e)}")
        raise
    
    if 'watchers' not in user_data:
        user_data['watchers'] = []
    
    watchers_text = "Выбранные наблюдатели:\n"
    for watcher_id in user_data['watchers']:
        for name, id in user_data['users']:
            if id == watcher_id:
                watchers_text += f"{name}\n"
                break
    
    if not user_data['watchers']:
        watchers_text += "Нет выбранных наблюдателей"

    confirm_kb = InlineKeyboardMarkup()
    confirm_kb.add(InlineKeyboardButton('Подтвердить', callback_data='confirm_yes'))
    confirm_kb.add(InlineKeyboardButton('Редактировать', callback_data='confirm_no'))
    confirm_kb.add(InlineKeyboardButton('Добавить наблюдателей', callback_data='select_watchers'))

    await bot.send_message(user_id, f"Пожалуйста, подтвердите или отредактируйте задачу:\n\n"
                                    f"Проект: {project_name}\n"
                                    f"Тема: {user_data['subject']}\n"
                                    f"Описание: {user_data['description']}\n"
                                    f"Исполнитель: {assignee_name}\n"
                                    f"Приоритет: {priority_name}\n"
                                    f"Дата завершения: {user_data.get('due_date', 'Пропущено')}\n"
                                    f"{watchers_text}\n",
                          reply_markup=confirm_kb)


@dp.callback_query_handler(lambda c: c.data == 'restart_issue_creation')
async def restart_issue_creation(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    logger.info(f"Restarting issue creation - user_id: {user_id}")
    user_issue_creation[user_id] = {}
    await handle_create_issue(callback_query)



@dp.callback_query_handler(lambda c: c.data == 'confirm_yes')
async def confirm_issue_creation(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.pop(user_id, None)
    if user_data is None or user_data['stage'] != 'confirm':
        return

    redmine = await get_redmine(user_id)
    project_id = user_data['project']
    assignee_id = user_data['assignee']
    subject = user_data['subject']
    description = user_data['description']
    priority = user_data['priority']
    due_date = user_data['due_date']

    if not priority:
        await bot.send_message(user_id, "Пожалуйста, выберите приоритет задачи.")
        return

    issue = await create_issue(
        redmine=redmine,
        project_id=project_id,
        subject=subject,
        description=description,
        assigned_to_id=assignee_id,
        priority_id=priority,
        due_date=due_date,
        watcher_user_ids=user_data['watchers']
    )

    logger.info(f"Issue created - user_id: {user_id}, issue_id: {issue.id}")

    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Посмотреть задачу", url=f"{redmine.url}/issues/{issue.id}")
    )

    await bot.send_message(user_id, f"Задача успешно создана!\n"
                                     f"Номер задачи: {issue.id}", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data == 'confirm_no')
async def reject_issue_creation(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'confirm':
        return
    edit_kb = InlineKeyboardMarkup()
    edit_kb.add(InlineKeyboardButton('Начать создание задачи с самого начала', callback_data='restart_issue_creation'))
    edit_kb.add(InlineKeyboardButton('Тема', callback_data='edit_subject'))
    edit_kb.add(InlineKeyboardButton('Описание', callback_data='edit_description'))
    edit_kb.add(InlineKeyboardButton('Исполнитель', callback_data='edit_assignee'))
    edit_kb.add(InlineKeyboardButton('Приоритет', callback_data='edit_priority'))
    edit_kb.add(InlineKeyboardButton('Дата завершения', callback_data='edit_due_date'))
    edit_kb.add(InlineKeyboardButton('Назад', callback_data='back_to_confirm'))
    await bot.send_message(user_id, "Выберите поле для редактирования:", reply_markup=edit_kb)

@dp.callback_query_handler(lambda c: c.data == 'back_to_confirm')
async def process_callback_back_to_confirm(callback_query: types.CallbackQuery):
    telegram_user_id = callback_query.from_user.id
    await confirm_issue(telegram_user_id)

@dp.callback_query_handler(lambda c: c.data == 'select_watchers')
async def process_callback_select_watchers(callback_query: types.CallbackQuery):
    await select_watchers(callback_query)


async def select_watchers(callback_query: types.CallbackQuery, page: int = 1):
    telegram_user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(telegram_user_id)
    if user_data is None or user_data['stage'] != 'confirm':
        return

    project_id = user_data['project']
    redmine =await get_redmine(telegram_user_id)
    project = redmine.redmine.project.get(project_id)
    user_data['users'] = get_list_assingee_users(project)  # в этом списке у нас уже все пользователи, их можно использовать как наблюдателей
    user_issue_creation[telegram_user_id] = user_data

    ITEMS_PER_PAGE = 5
    total_pages = (len(user_data['users']) - 1) // ITEMS_PER_PAGE + 1

    start_index = (page - 1) * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    users_slice = user_data['users'][start_index:end_index]

    kb = InlineKeyboardMarkup(row_width=1)
    for user in users_slice:
        name, user_id = user
        callback_data = f'select_watcher_{user_id}'
        if user_id in user_data['watchers']:
            callback_data += '_selected'  # добавляем суффикс '_selected', если пользователь уже выбран как наблюдатель
            kb.add(InlineKeyboardButton(f'{name} 🟢', callback_data=callback_data))
        else:
            kb.add(InlineKeyboardButton(name, callback_data=callback_data))
    if page > 1:
        kb.insert(InlineKeyboardButton('Previous', callback_data=f'select_previous_page:{page-1}:{project_id}'))
    if end_index < len(user_data['users']):
        kb.add(InlineKeyboardButton('Next', callback_data=f'select_next_page:{page+1}:{project_id}'))

    kb.add(InlineKeyboardButton('Подтвердить', callback_data='confirm_watchers'))
    kb.add(InlineKeyboardButton('Назад', callback_data='back_to_confirm'))

    await bot.edit_message_text('Выберите наблюдателей:',
                                chat_id=telegram_user_id,
                                message_id=callback_query.message.message_id,
                                reply_markup=kb)

    
@dp.callback_query_handler(lambda c: c.data.startswith('select_watcher_'))
async def process_callback_select_watcher(callback_query: types.CallbackQuery):
    telegram_user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(telegram_user_id)

    watcher_id = int(callback_query.data.split('_')[2])
    if watcher_id in user_data['watchers']:
        user_data['watchers'].remove(watcher_id)
    else:
        user_data['watchers'].append(watcher_id)

    await select_watchers(callback_query)  # обновим страницу, чтобы пользователь мог продолжить выбор


@dp.callback_query_handler(lambda c: c.data.startswith('select_next_page:'))
async def process_callback_select_next_page(callback_query: types.CallbackQuery):
    _, page, project_id = callback_query.data.split(':')
    page = int(page)
    await bot.answer_callback_query(callback_query.id)  
    await select_watchers(callback_query, page)


@dp.callback_query_handler(lambda c: c.data.startswith('select_previous_page:'))
async def process_callback_select_previous_page(callback_query: types.CallbackQuery):
    _, page, project_id = callback_query.data.split(':')
    page = int(page)
    await bot.answer_callback_query(callback_query.id)  
    await select_watchers(callback_query, page)


@dp.callback_query_handler(lambda c: c.data == 'confirm_watchers')
async def process_callback_confirm_watchers(callback_query: types.CallbackQuery):
    telegram_user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(telegram_user_id)

    # переключим стадию на 'confirm' и вернем пользователя на страницу подтверждения
    user_data['stage'] = 'confirm'

    await bot.send_message(telegram_user_id, 'Наблюдатели успешно выбраны.')
    await confirm_issue(telegram_user_id)



@dp.callback_query_handler(lambda c: c.data == 'edit_assignee')
async def edit_assignee(callback_query: types.CallbackQuery, page: int = 1):
    telegram_user_id = callback_query.from_user.id  
    user_data = user_issue_creation.get(telegram_user_id)
    if user_data is None or user_data['stage'] != 'confirm':
        return

    project_id = user_data['project']
    redmine =await get_redmine(telegram_user_id)
    project = redmine.redmine.project.get(project_id)
    user_data['users'] = get_list_assingee_users(project)
    user_issue_creation[telegram_user_id] = user_data  

    ITEMS_PER_PAGE = 5  
    total_pages = (len(user_data['users']) - 1) // ITEMS_PER_PAGE + 1

    start_index = (page - 1) * ITEMS_PER_PAGE
    end_index = start_index + ITEMS_PER_PAGE
    users_slice = user_data['users'][start_index:end_index]

    kb = InlineKeyboardMarkup(row_width=1)
    for user in users_slice:
        name, user_id = user
        kb.add(InlineKeyboardButton(name, callback_data=f'edit_user_{user_id}'))
    if page > 1:
        kb.insert(InlineKeyboardButton('Previous', callback_data=f'edit_previous_page:{page-1}:{project_id}'))
    if end_index < len(user_data['users']):
        kb.add(InlineKeyboardButton('Next', callback_data=f'edit_next_page:{page+1}:{project_id}'))

    await bot.send_message(telegram_user_id, 'Выберите нового исполнителя:', reply_markup=kb)
    
    await bot.delete_message(callback_query.message.chat.id, callback_query.message.message_id)



@dp.callback_query_handler(lambda c: c.data.startswith('edit_next_page:'))
async def process_callback_edit_next_page(callback_query: types.CallbackQuery):
    _, page, project_id = callback_query.data.split(':')
    page = int(page)
    await bot.answer_callback_query(callback_query.id)  
    await bot.edit_message_reply_markup(callback_query.message.chat.id, callback_query.message.message_id)  
    await edit_assignee(callback_query, page)


@dp.callback_query_handler(lambda c: c.data.startswith('edit_previous_page:'))
async def process_callback_edit_previous_page(callback_query: types.CallbackQuery):
    _, page, project_id = callback_query.data.split(':')
    page = int(page)
    await bot.answer_callback_query(callback_query.id)  
    await bot.edit_message_reply_markup(callback_query.message.chat.id, callback_query.message.message_id)  
    await edit_assignee(callback_query, page)


@dp.callback_query_handler(lambda c: c.data.startswith('edit_user_'))
async def process_callback_edit_assignee(callback_query: types.CallbackQuery):
    telegram_user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(telegram_user_id)

    assignee_id = int(callback_query.data.split('_')[2])
    user_data['assignee'] = assignee_id
    user_data['stage'] = 'confirm'

    await bot.send_message(telegram_user_id, 'Исполнитель успешно изменен.')

    await confirm_issue(telegram_user_id)


@dp.callback_query_handler(lambda c: c.data == 'edit_subject')
async def edit_subject(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'confirm':
        return

    user_data['stage'] = 'edit_subject'
    user_issue_creation[user_id] = user_data

    await bot.send_message(user_id, 'Введите новую тему задачи:')

@dp.message_handler(lambda message: user_issue_creation.get(message.from_user.id, {}).get('stage') == 'edit_subject')
async def process_edit_subject(message: types.Message):
    user_id = message.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'edit_subject':
        return

    user_data['subject'] = message.text
    user_data['stage'] = 'confirm'
    user_issue_creation[user_id] = user_data
    await bot.send_message(user_id, 'Тема успешно изменена.')
    await confirm_issue(user_id)


@dp.callback_query_handler(lambda c: c.data == 'edit_description')
async def edit_description(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'confirm':
        return

    user_data['stage'] = 'edit_description'
    user_issue_creation[user_id] = user_data

    await bot.send_message(user_id, 'Введите новое описание задачи:')

@dp.message_handler(lambda message: user_issue_creation.get(message.from_user.id, {}).get('stage') == 'edit_description')
async def process_edit_description(message: types.Message):
    user_id = message.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'edit_description':
        return

    user_data['description'] = message.text
    user_data['stage'] = 'confirm'
    user_issue_creation[user_id] = user_data
    await bot.send_message(user_id, 'Описание успешно изменено.')
    await confirm_issue(user_id)


@dp.callback_query_handler(lambda c: c.data == 'edit_priority')
async def edit_priority(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'confirm':
        return

    user_data['stage'] = 'edit_priority'
    user_issue_creation[user_id] = user_data

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton('Low', callback_data='edit_priority_low'))
    kb.add(InlineKeyboardButton('Normal', callback_data='edit_priority_normal'))
    kb.add(InlineKeyboardButton('High', callback_data='edit_priority_high'))
    kb.add(InlineKeyboardButton('Urgent', callback_data='edit_priority_urgent'))
    kb.add(InlineKeyboardButton('Immediate', callback_data='edit_priority_immediate'))
    await bot.send_message(user_id, 'Выберите новый приоритет задачи:', reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data.startswith('edit_priority_'))
async def process_callback_edit_priority(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'edit_priority':
        return

    priority_mapping = {
        'low': 1,
        'normal': 2,
        'high': 3,
        'urgent': 4,
        'immediate': 5
    }
    priority = callback_query.data.split('_')[2]
    priority_value = priority_mapping.get(priority.lower())

    if priority_value is None:
        await bot.answer_callback_query(callback_query.id, text='Неверное значение приоритета.')
        return

    user_data['priority'] = priority_value
    user_data['priorityname'] = priority
    user_data['stage'] = 'confirm'
    user_issue_creation[user_id] = user_data
    await bot.send_message(user_id, 'Приоритет успешно изменен.')
    await confirm_issue(user_id)

@dp.callback_query_handler(lambda c: c.data == 'edit_due_date')
async def prompt_edit_due_date(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'confirm':
        return
    user_data['stage'] = 'edit_due_date'
    user_issue_creation[user_id] = user_data
    await bot.send_message(
        user_id, 
        'Введите дату завершения задачи в формате ДД.ММ.ГГГГ или ДД ММ ГГГГ', 
        reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton('Пропустить', callback_data='edit_skip_due_date'))
    )

@dp.callback_query_handler(lambda c: c.data == 'edit_skip_due_date')
async def edit_due_date_skip(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'edit_due_date':
        return
    user_data['due_date'] = None
    user_data['stage'] = 'confirm'
    user_issue_creation[user_id] = user_data
    await bot.send_message(user_id, 'Дата завершения пропущена.')
    await confirm_issue(user_id)

@dp.message_handler(lambda message: user_issue_creation.get(message.from_user.id, {}).get('stage') == 'edit_due_date')
async def set_due_date(message: types.Message):
    user_id = message.from_user.id
    user_data = user_issue_creation.get(user_id)
    if user_data is None or user_data['stage'] != 'edit_due_date':
        return

    due_date_str = message.text
    
    # Определите все форматы, которые вы хотите поддерживать
    date_formats = ["%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d %m %Y"]
    due_date = None
    
    for fmt in date_formats:
        try:
            due_date = datetime.strptime(due_date_str, fmt).date()
            break  # Выход из цикла, если парсинг удался
        except ValueError:
            pass  # Продолжаем цикл, если парсинг не удался
    
    if due_date is None:
        await bot.send_message(
            user_id, 
            'Неверный формат даты. Пожалуйста, введите дату в одном из форматов:ДД.ММ.ГГГГ или ДД ММ ГГГГ, или выберите Пропустить.', 
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton('Пропустить', callback_data='edit_skip_due_date'))
        )
        return
    
    if due_date < datetime.now().date():
        await bot.send_message(
            user_id, 
            'Дата не может быть меньше текущей. Пожалуйста, введите корректную дату.',
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton('Пропустить', callback_data='edit_skip_due_date'))
        )
        return
    
    user_data['due_date'] = due_date.strftime("%Y-%m-%d")
    logger.info(f"Due date set - user_id: {user_id}, due_date: {due_date}")
    user_data['stage'] = 'confirm'
    await confirm_issue(user_id)

@dp.message_handler(lambda message: user_issue_creation.get(message.from_user.id, {}).get('stage') == 'edit_due_date')
async def edit_due_date_invalid(message: types.Message):
    user_id = message.from_user.id
    await bot.send_message(user_id, 'Формат даты неверен. Пожалуйста, введите дату в форматеДД.ММ.ГГГГ или ДД ММ ГГГГ или выберите Пропустить.', reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton('Пропустить', callback_data='edit_skip_due_date')))








@dp.message_handler(Text(equals='Создать задачу 🛠️'))
async def create_issue_command_handler(message: types.Message):
    await handle_create_issue(message)






async def get_users(page=1):
    logger.info(f"Get users - page: {page}")
    redmine =await get_redmine(None)
    cache_key = f"users_{page}"

    async def users_request():
        return redmine.redmine.user.filter(offset=(page - 1) * PAGE_SIZE, limit=PAGE_SIZE)

    return await cached_request(cache_key, users_request)


async def send_comment(issue_id, user_id, comment_text):
    logger.info(f"Send comment - issue_id: {issue_id}, user_id: {user_id}")
    redmine =await get_redmine(user_id)
    try:
        redmine.redmine.issue.update(issue_id, notes=comment_text)
        # Удаляем кэш для задачи после отправки комментария
        cache_key = f"issue_{issue_id}"
        if cache_key in cache:
            del cache[cache_key]
        await bot.send_message(user_id, "Комментарий успешно отправлен.\nДля продолжения работы вызовите меню, расположенное в правом нижнем углу ↘️")
    except Exception as e:
        logger.error(f"Error sending comment: {e}")
        await bot.send_message(user_id, "Ошибка при отправке комментария. Пожалуйста, попробуйте снова.")
        raise


PAGE_SIZE = 10

async def get_projects(user_id):
    logger.info("Get projects")
    redmine =await get_redmine(user_id)
    cache_key = f"projects"

    async def projects_request():
        all_projects = redmine.redmine.project.all()
        return all_projects

    return await cached_request(cache_key, projects_request)







# Словарь для кэширования
cache = {}

# Время жизни кэша (в секундах)
CACHE_EXPIRY = 0

def update_cache(cache_key, result):
    cache[cache_key] = (time.time(), result)


async def cached_request(cache_key, request_func):
    if cache_key in cache:
        timestamp, result = cache[cache_key]
        if time.time() - timestamp <= CACHE_EXPIRY:
            return result

    result = await request_func()
    cache[cache_key] = (time.time(), result)
    return result

from enum import Enum


class IssueFilter(Enum):
    is_assigned_by_me = 'assignedbyme_'
    is_watching = 'watching_'
    is_assigned = 'assignedtome_'


async def get_all_issues(user_id, issue_filter: IssueFilter):
    logger.info(f"Get all issues - user_id: {user_id}, filter: {issue_filter}")
    redmine =await get_redmine(user_id)
    user = await get_user(redmine, 'me')

    # We need to differentiate between the user's personal ID and the group IDs
    personal_id = user.id
    group_ids = [group.id for group in user.groups]

    issues = []

    if issue_filter == IssueFilter.is_assigned:
        # Add issues assigned to the user or one of their groups
        issues += list(redmine.redmine.issue.filter(assigned_to_id=personal_id, status_id='*'))
        for id in group_ids:
            issues += list(redmine.redmine.issue.filter(assigned_to_id=id, status_id='*'))
    if issue_filter == IssueFilter.is_watching:
        # Add issues watched by the user or one of their groups
        issues += list(redmine.redmine.issue.filter(watcher_id=personal_id, status_id='*'))
        for id in group_ids:
            issues += list(redmine.redmine.issue.filter(watcher_id=id, status_id='*'))
    if issue_filter == IssueFilter.is_assigned_by_me:
        # Add issues created by the user
        issues += list(redmine.redmine.issue.filter(author_id=personal_id, status_id='*'))

    # Filter out issues that are closed
    issues = [issue for issue in issues if not issue.status.is_closed]

    return issues


async def get_projects_with_tasks(callback_query: types.CallbackQuery, callback_prefix):
    user_id = callback_query.from_user.id
    redmine = await get_redmine(user_id)
    all_projects = redmine.redmine.project.all()

    cache_key = f"projects_with_tasks_{user_id}_{callback_prefix}"

    async def projects_request():
        # Create a list to store projects with tasks
        projects_with_tasks = []
        issue_counts = {}

        issues = await get_all_issues(user_id, issue_filter=IssueFilter(callback_prefix))

        # Group issues by project
        issues_by_project = {}
        for issue in issues:
            if issue.project.id not in issues_by_project:
                issues_by_project[issue.project.id] = []
            issues_by_project[issue.project.id].append(issue)

        # Iterate over all projects and add those with tasks to projects_with_tasks
        for project in all_projects:
            if project.id in issues_by_project:
                issue_counts[project.id] = len(issues_by_project[project.id])
                projects_with_tasks.append(project)

        return projects_with_tasks, len(all_projects), issue_counts

    return await cached_request(cache_key, projects_request)





async def get_issue(issue_id, user_id):
    logger.info(f"Get issue - issue_id: {issue_id}, user_id: {user_id}")
    redmine =await get_redmine(user_id)
    issue = redmine.redmine.issue.get(issue_id)
    return issue

def get_from_cache(cache_key):
    if cache_key in cache:
        timestamp, result = cache[cache_key]
        if time.time() - timestamp <= CACHE_EXPIRY:
            return result
    return None

async def view_issues(user_id, page=1, issue_filter=None, project_id=None):
    logger.info(f"View issues - user_id: {user_id}, page: {page}, issue_filter: {issue_filter}")
    redmine = await get_redmine(user_id)
    if redmine is None:
        raise ValueError("Redmine instance not found.")

    user = await get_user(redmine, 'me')
    cache_key = f"view_issues_{user_id}_{page}_{issue_filter.value if issue_filter else ''}_{project_id}"

    cached_data = get_from_cache(cache_key)
    if cached_data is not None:
        return cached_data

    user_id = user.id
    group_ids = [group.id for group in user.groups]

    issues = []
    
    async def issues_request():
        nonlocal issues
        if issue_filter == IssueFilter.is_assigned_by_me:
            issues += list(redmine.redmine.issue.filter(project_id=project_id, author_id=user_id, status_id='*'))
        elif issue_filter == IssueFilter.is_assigned:
            issues += list(redmine.redmine.issue.filter(project_id=project_id, assigned_to_id=user_id, status_id='*'))
            for group_id in group_ids:
                issues += list(redmine.redmine.issue.filter(project_id=project_id, assigned_to_id=group_id, status_id='*'))
        elif issue_filter == IssueFilter.is_watching:
            issues += list(redmine.redmine.issue.filter(project_id=project_id, watcher_id=user_id, status_id='*'))
            for group_id in group_ids:
                issues += list(redmine.redmine.issue.filter(project_id=project_id, watcher_id=group_id, status_id='*'))

        # Filter out issues that are closed
        issues = [issue for issue in issues if not issue.status.is_closed]

        start_index = (page - 1) * ITEMS_PER_PAGE
        end_index = start_index + ITEMS_PER_PAGE
        paginated_issues = issues[start_index:end_index]

        # Calculate total_pages based on the paginated issues
        total_pages = (len(issues) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

        result = paginated_issues, total_pages
        return result

    result = await cached_request(cache_key, issues_request)

    return result



@dp.message_handler(lambda message: message.text == 'Просмотр задач 👁️')
async def handle_task_view(message: types.Message):
    markup = InlineKeyboardMarkup()
    markup.add(
         InlineKeyboardButton("Мне поручено", callback_data="assignedtome_selectproject_1"),
         InlineKeyboardButton("Я наблюдаю", callback_data="watching_selectproject_1"),
         InlineKeyboardButton("Я поручил", callback_data="assignedbyme_selectproject_1"),
         InlineKeyboardButton("Поиск задачи 🔎", callback_data="search_")  
    )
    await bot.send_message(message.chat.id, "Выберите тип задач:", reply_markup=markup)





@dp.callback_query_handler(lambda c: c.data.startswith('assignedtome_selectproject_'))
async def assigned_to_me_select_project_page_callback_handler(query: types.CallbackQuery):
    await bot.answer_callback_query(query.id)
    page = int(query.data.split('_')[2])  # номер страницы теперь находится здесь
    await handle_select_project(query, 'assignedtome_')

@dp.callback_query_handler(lambda c: c.data.startswith('watching_selectproject_'))
async def watching_select_project_page_callback_handler(query: types.CallbackQuery):
    await bot.answer_callback_query(query.id)
    page = int(query.data.split('_')[2])  # номер страницы теперь находится здесь
    await handle_select_project(query, 'watching_')

@dp.callback_query_handler(lambda c: c.data.startswith('assignedbyme_selectproject_'))
async def assigned_by_me_select_project_page_callback_handler(query: types.CallbackQuery):
    await bot.answer_callback_query(query.id)
    page = int(query.data.split('_')[2])  # номер страницы теперь находится здесь
    await handle_select_project(query, 'assignedbyme_')

async def handle_select_project(callback_query: types.CallbackQuery, callback_prefix, page=1):
    user_id = callback_query.from_user.id
    projects, total_page, issue_counts = await get_projects_with_tasks(callback_query, callback_prefix)
    
 
    issues = await get_all_issues(user_id, issue_filter=IssueFilter(callback_prefix))   
    
    for project in projects:
        project_issues = [issue for issue in issues if issue.project.id == project.id]
        issue_counts[project.id] = len(project_issues)
    
    if not projects: 
        await bot.send_message(callback_query.from_user.id, "Проектов не найдено.")
        return

    kb = InlineKeyboardMarkup()
    for project in projects:

        kb.add(InlineKeyboardButton(f"{project.name} (задач: {issue_counts[project.id]})", 
                                    callback_data=f'{callback_prefix}project_{project.id}~{project.name}'))
        

    
    chat_id = callback_query.message.chat.id
    previous_message = get_from_cache(f"{callback_prefix}")
    

    
    message = await bot.send_message(chat_id=chat_id, text=f'Выберите проект:', reply_markup=kb)
    update_cache(f"{callback_prefix}", message.message_id)








async def process_callback_project(callback_query: types.CallbackQuery, callback_data_prefix: str, task_desc: str, issue_filter=None):
    logger.info("Project selected")
    await bot.answer_callback_query(callback_query.id)
    
    # Используем '~' в качестве разделителя
    split_data = callback_query.data.split(f'{callback_data_prefix}project_')[1].split("~")
    project_id = int(split_data[0])
    project_name = "~".join(split_data[1:])
    
    # Using the refactored view_issues function with issue_filter parameter
    issues, total_issues = await view_issues(callback_query.from_user.id, page=1, issue_filter=issue_filter, project_id=project_id)
    
    await bot.edit_message_text(f"Задачи, {task_desc} в проекте {project_name}:",
                                chat_id=callback_query.from_user.id,
                                message_id=callback_query.message.message_id,
                                reply_markup=issues_pagination_keyboard(issues, f'{callback_data_prefix}', 1, total_issues, project_id))





@dp.callback_query_handler(lambda c: c.data.startswith('assignedtome_project_'))
async def process_callback_project_assigned(callback_query: types.CallbackQuery):
    await process_callback_project(callback_query, 'assignedtome_', "которые вам поручены", issue_filter=IssueFilter.is_assigned)

@dp.callback_query_handler(lambda c: c.data.startswith('watching_project_'))
async def process_callback_project_watching(callback_query: types.CallbackQuery):
    await process_callback_project(callback_query, 'watching_', "которые вы наблюдаете", issue_filter=IssueFilter.is_watching)

@dp.callback_query_handler(lambda c: c.data.startswith('assignedbyme_project_'))
async def process_callback_project_assigned_by_me(callback_query: types.CallbackQuery):
    await process_callback_project(callback_query, 'assignedbyme_', "которые вы поручили", issue_filter=IssueFilter.is_assigned_by_me)

async def common_callback_handler(query, task_desc, issue_filter=None):
    await bot.answer_callback_query(query.id)
    page, project_id = map(int, query.data.split('_')[1:3])
    issues, total_issues = await view_issues(query.from_user.id, page=page, issue_filter=issue_filter, project_id=project_id)
    await bot.edit_message_text(f"Задачи, {task_desc}:",
                                chat_id=query.from_user.id,
                                message_id=query.message.message_id,
                                reply_markup=issues_pagination_keyboard(issues, issue_filter.value, page, total_issues, project_id))

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('assignedtome_') and int(c.data.split('_')[1]) > 0)
async def assigned_to_me_callback_handler(query: types.CallbackQuery):
    await common_callback_handler(query, "которые вам поручены", issue_filter=IssueFilter.is_assigned)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('watching_') and int(c.data.split('_')[1]) > 0)
async def watching_callback_handler(query: types.CallbackQuery):
    await common_callback_handler(query, "которые вы наблюдаете", issue_filter=IssueFilter.is_watching)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('assignedbyme_') and int(c.data.split('_')[1]) > 0)
async def assigned_by_me_callback_handler(query: types.CallbackQuery):
    await common_callback_handler(query, "которые вы поручили", issue_filter=IssueFilter.is_assigned_by_me)

    
def issues_pagination_keyboard(issues, callback_data_prefix, current_page, total_pages, project_id):
    keyboard = InlineKeyboardMarkup()

    # Убедитесь, что issues не пуст и не содержит None или другие нежелательные значения
    if issues:
        for issue in issues:
            if issue is not None:  # Проверка на None или другие нежелательные значения
                keyboard.add(InlineKeyboardButton(f"#{issue.id} {issue.subject} - {issue.status.name}", callback_data=f"viewissue_{issue.id}"))
    else:
        # Возможно, вы хотите добавить кнопку или сообщение, указывающее, что проблем не найдено
        keyboard.add(InlineKeyboardButton("No issues found", callback_data="no_issues", disabled=True))

    if total_pages > 1:
        buttons_row = []
        if current_page > 1:
            buttons_row.append(InlineKeyboardButton("◀️Prev", callback_data=f"{callback_data_prefix}{current_page - 1}_{project_id}"))
        buttons_row.append(InlineKeyboardButton(f"Страница {current_page}/{total_pages}", callback_data="dummy_data", disabled=True))
        if current_page < total_pages:
            buttons_row.append(InlineKeyboardButton("Next▶️", callback_data=f"{callback_data_prefix}{current_page + 1}_{project_id}"))
        keyboard.row(*buttons_row)

    return keyboard



    
    

class SearchTask(StatesGroup):
    waiting_for_task_id = State()

def cancel_button():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Отмена ввода", callback_data="cancel_search"))
    return markup

@dp.callback_query_handler(lambda c: c.data == 'search_')
async def handle_search_task(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(user_id, "Введите номер задачи или ссылку на задачу.", reply_markup=cancel_button())

    await SearchTask.waiting_for_task_id.set()

@dp.message_handler(state=SearchTask.waiting_for_task_id)
async def handle_search_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_notifications[user_id] = message
    await handle_search(user_id)
    await state.finish()  # Закончить текущее состояние

async def handle_search(user_id):
    message = user_notifications[user_id]  # Получаем объект сообщения из переменной user_notifications
    text = message.text.strip()

    if text.isdigit():
        issue_id = int(text)
    elif text.startswith('#') and text[1:].isdigit(): 
        issue_id = int(text[1:])
    else:
        match = re.search(r'(https?:\/\/helpdesk.physics.itmo.ru\/issues\/(\d+))', text)  
        if match is not None:
            issue_id = int(match.group(2))  
        else:
            await bot.send_message(message.chat.id, "Неправильный формат ввода. Пожалуйста, введите номер задачи или ссылку на задачу.")
            return

    try:
        issue = await get_issue(issue_id, message.from_user.id)
        journal_entries = list(issue.journals)
        comments = [(entry.user.name, entry.notes) for entry in journal_entries if entry.notes] 
        if comments:
            formatted_comments = '\n\n'.join([f"{name} писал(а):\n{comment}" for name, comment in comments])
            text = f"Задача #{issue.id} - {issue.status.name}\n{issue.subject}\n\nСтатус:\n{issue.status.name}\n\nОписание:\n{issue.description}\n\nКомментарии:\n{formatted_comments}"
        else:
            text = f"Задача #{issue.id} - {issue.status.name}\n{issue.subject}\n\nСтатус:\n{issue.status.name}\nОписание:\n{issue.description}"

        await bot.send_message(message.chat.id, text, reply_markup=comment_buttons(issue_id))
    except KeyError:
        await bot.send_message(user_id, "Произошла ошибка при обработке поиска задачи. Пожалуйста, повторите попытку.")




@dp.callback_query_handler(lambda c: c.data == 'cancel_search', state=SearchTask.waiting_for_task_id)
async def handle_cancel_search(callback_query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await bot.answer_callback_query(callback_query.id, "Поиск отменен")
    await bot.send_message(callback_query.from_user.id, "Поиск задачи отменен.")





# def issues_pagination_keyboard(issues, callback_data_prefix, current_page, total_issues, project_id):
#     keyboard = InlineKeyboardMarkup()
#     for issue in issues:
#         keyboard.add(InlineKeyboardButton(f"#{issue.id} {issue.subject} - {issue.status.name}", callback_data=f"viewissue_{issue.id}"))
#     if total_issues > current_page * ITEMS_PER_PAGE:
#         keyboard.add(InlineKeyboardButton("Следующая страница", callback_data=f"{callback_data_prefix}{current_page + 1}_{project_id}"))
#     if current_page > 1:
#         keyboard.add(InlineKeyboardButton("Предыдущая страница", callback_data=f"{callback_data_prefix}{current_page - 1}_{project_id}"))
#     return keyboard




@dp.callback_query_handler(lambda c: c.data.startswith('viewissue_'))
async def view_issue_callback_handler(query: types.CallbackQuery):
    logger.info("view_issue_callback_handler called")  
    await bot.answer_callback_query(query.id)
    issue_id = query.data.split('_')[1]
    issue = await get_issue(issue_id, query.from_user.id)
    journal_entries = list(issue.journals)
    comments = [(entry.user.name, entry.notes) for entry in journal_entries if entry.notes] 
    # Находим имя пользователя и его комментарий

    if comments:
        formatted_comments = '\n\n'.join([f"{name} писал(а):\n{comment}" for name, comment in comments])  
        # Форматируем каждый комментарий с именем пользователя
        text = f"Задача #{issue.id} - {issue.status.name}\n{issue.subject}\n\nСтатус:\n{issue.status.name}\n\nИсполнитель:\n{issue.assigned_to.name}\n\nОписание:\n{issue.description}\n\nКомментарии:\n{formatted_comments}"
    else:
        text = f"Задача #{issue.id} - {issue.status.name}\n{issue.subject}\n\nСтатус:\n{issue.status.name}\n\nИсполнитель:\n{issue.assigned_to.name}\nОписание:\n{issue.description}"

    await bot.send_message(query.from_user.id, text, reply_markup=comment_buttons(issue_id))


def comment_buttons(issue_id):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("Добавить комментарий", callback_data=f"comment_{issue_id}"))
    keyboard.add(InlineKeyboardButton(text="Изменить статус", callback_data=f"edit_status_menu_{issue_id}"))

    keyboard.add(InlineKeyboardButton("Посмотреть задачу", url=f"{REDMINE_URL}/issues/{issue_id}"))
    return keyboard


@dp.callback_query_handler(lambda c: c.data.startswith('comment_'))
async def comment_callback_handler(query: types.CallbackQuery):
    logger.info("comment_callback_handler called")  
    await bot.answer_callback_query(query.id)
    issue_id = query.data.split('_')[1]
    user_notifications[query.from_user.id] = issue_id
    await bot.send_message(query.from_user.id, "Введите текст комментария:", reply_markup=cancel_button_comment())

def cancel_button_comment():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Отмена ввода", callback_data="cancel_comment"))
    return markup

@dp.callback_query_handler(lambda c: c.data == 'cancel_comment')
async def handle_cancel_comment(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id in user_notifications:
        del user_notifications[user_id]
    await bot.answer_callback_query(callback_query.id, "Ввод комментария отменён")
    await bot.send_message(user_id, "Ввод комментария отменён.")

@dp.message_handler(lambda message: message.text == 'Начало')
async def handle_start(message: types.Message):
    await start(message)


jobs = {}
user_redmines = {}
last_state = {}
last_check_times = {}



from datetime import datetime, timedelta



import traceback

def to_dict(issue):
    journals = [(journal.user.name, journal.notes) for journal in issue.journals if journal.notes]
    last_user, last_journal = journals[-1] if journals else (None, None)
    last_journal_with_user = f"{last_user}: {last_journal}" if last_user else last_journal
    return {
        'id': issue.id,
        'subject': issue.subject,
        'status': issue.status.name,
        'description': issue.description,
        'last_journal': last_journal_with_user,
    }





async def fetch_issues(redmine, personal_id, group_ids, updated_since):
    logging.info(f"Fetching issues for personal_id: {personal_id} and groups: {group_ids} updated since {updated_since}")
    # Fetching issues based on different criteria
    issues_assigned = list(redmine.redmine.issue.filter(status_id='*', updated_on=f">={updated_since}", assigned_to_id=personal_id))
    issues_assigned_to_groups = []
    for group_id in group_ids:
        issues_assigned_to_groups += list(redmine.redmine.issue.filter(status_id='*', updated_on=f">={updated_since}", assigned_to_id=group_id))

    issues_authored = list(redmine.redmine.issue.filter(status_id='*', updated_on=f">={updated_since}", author_id=personal_id))
    issues_watched = list(redmine.redmine.issue.filter(status_id='*', updated_on=f">={updated_since}", watcher_id=personal_id))
    
    # Combine all issues and remove duplicates
    all_issues = issues_assigned + issues_authored + issues_watched + issues_assigned_to_groups
    unique_issues = {issue.id: issue for issue in all_issues}
    
    return list(unique_issues.values())


async def check_updates(user_id):
    try:
        logging.info(f"Starting check_updates for user_id: {user_id}")

        redmine = await get_redmine(user_id)
        user = await get_user(redmine, 'me')
        
        personal_id = user.id
        group_ids = [group.id for group in user.groups]
        logging.info(f"Got personal_id: {personal_id} and group_ids: {group_ids} for user_id: {user_id}")

        if user_id in last_check_times:
            last_check_time = last_check_times[user_id]
        else:
            last_check_time = datetime.utcnow() - timedelta(days=30)

        updated_since = last_check_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        all_issues = await fetch_issues(redmine, personal_id, group_ids, updated_since)

        logging.info(f"Fetched {len(all_issues)} issues for user_id: {user_id} since {updated_since}")

        if user_id not in last_state:
            last_state[user_id] = {}
            for issue in all_issues:
                issue_id = str(issue.id)
                detailed_issue = redmine.redmine.issue.get(issue_id, include='journals')
                last_state[user_id][issue_id] = to_dict(detailed_issue)
            logging.info(f"Initialized last_state[{user_id}] with current issues")
            last_check_times[user_id] = datetime.utcnow()
            return

        for issue in all_issues:
            issue_id = str(issue.id)
            detailed_issue = redmine.redmine.issue.get(issue_id, include='journals')
            new_issue = to_dict(detailed_issue)

            if issue_id not in last_state[user_id]:
                logging.info(f"New issue_id: {issue_id} for user_id: {user_id}")
                message = f"У вас новая задача или обновлена старая!\nЗадача #{issue_id}\nТема: {issue.subject}\nОписание: {issue.description}\n"
                new_comment = new_issue.get('last_journal')
                if new_comment:
                    message += f"Новый комментарий от: {new_comment}\n"

                await bot.send_message(user_id, message, reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text="Добавить комментарий", callback_data=f"comment_{issue_id}")], # <-- добавлена кнопка
                        [types.InlineKeyboardButton(text="Просмотреть задачу", url=f"{redmine.url}/issues/{issue_id}")]
                    ]))
            else:
                differences = ""
                new_comment = None

                if issue_id in last_state[user_id]:
                    old_issue = last_state[user_id][issue_id]
                    for key in new_issue:
                        if old_issue.get(key) != new_issue.get(key):
                            logging.info(f"Found difference in key: {key} for issue_id: {issue_id}")
                            if key == 'last_journal':
                                new_comment = new_issue.get(key)
                            else:
                                differences += f"{key} изменено с '{old_issue.get(key)}' на '{new_issue.get(key)}'\n"

                message = f"Задача #{issue_id}\nТема: {issue.subject} обновлена:\nОписание: {issue.description}\n"
                if differences:
                    message += differences
                if new_comment:
                    message += f"Новый комментарий от: {new_comment}\n"

                await bot.send_message(user_id, message, reply_markup=types.InlineKeyboardMarkup(
                    inline_keyboard=[
                        [types.InlineKeyboardButton(text="Добавить комментарий", callback_data=f"comment_{issue_id}")],
                        [types.InlineKeyboardButton(text="Просмотреть задачу", url=f"{redmine.url}/issues/{issue_id}")]
                    ]))

                last_state[user_id][issue_id] = new_issue


            last_check_times[user_id] = datetime.utcnow()

    except Exception as e:
        logging.error(f"Error in checking updates for user {user_id}: {e}")
        logging.error(traceback.format_exc())

@dp.callback_query_handler(lambda c: c.data.startswith('edit_status_'))
async def process_callback_edit_status(callback_query: types.CallbackQuery):
    logger.info("process_callback_edit_status called")
    await bot.answer_callback_query(callback_query.id)
    
    data_parts = callback_query.data.split('_')
    action = data_parts[2]
    issue_id = data_parts[3]
    
    # Маппинг статусов
    status_mapping = {
        'new': 1,
        'feedback': 4,
        'in progress': 2,
        'completed': 6,
        'verified': 7,
        'expired': 8,
        'stalled': 9
    }
    
    try:
        issue = await get_issue(issue_id, callback_query.from_user.id) # Изменено на get_issue
    except Exception as e:
        logger.error(f"Error getting issue: {e}")
        await bot.send_message(callback_query.from_user.id, "Не удалось получить задачу. Пожалуйста, свяжитесь с администратором.")
        return
    
    if action == "menu":
        # Создание inline кнопок для выбора статусов
        status_buttons = [InlineKeyboardButton(status.capitalize(), callback_data=f'edit_status_{status}_{issue_id}') for status in status_mapping.keys()]
        status_kb = InlineKeyboardMarkup(row_width=2).add(*status_buttons)

        await bot.send_message(callback_query.from_user.id, 'Выберите новый статус задачи:', reply_markup=status_kb)
        
    else:
        status = action
        status_value = status_mapping.get(status.lower())

        if status_value is None:
            await bot.answer_callback_query(callback_query.id, text='Неверное значение статуса.')
            return
        
        # Изменение статуса задачи
        try:
            issue.status_id = status_value
            issue.save()
        except Exception as e:
            logger.error(f"Failed to update the issue status: {e}, {type(e).__name__}")
            await bot.send_message(callback_query.from_user.id, f"Не удалось изменить статус задачи. Возможно, этот вариант статуса вам недоступен или произошла ошибка. Детали ошибки: {e}")
            return

        await bot.answer_callback_query(callback_query.id, text='Статус задачи успешно изменен.')
        await bot.send_message(callback_query.from_user.id, f"Статус задачи #{issue_id} успешно изменен на {status}.")








async def notification_job():
    while True:
        try:
            # Проверяем все обновления для всех пользователей
            for user_id in list(user_notifications_status.keys()):
                await check_updates(user_id)
            await asyncio.sleep(66)
        except Exception as e:
            logging.error(f"Error in notification job: {e}")
            logging.error(traceback.format_exc())
            await asyncio.sleep(66)

@dp.callback_query_handler(lambda c: c.data == 'enable_notifications')
async def enable_notifications(query: types.CallbackQuery):
    logger.info("enable_notifications called")  
    await bot.answer_callback_query(query.id)
    user_id = query.from_user.id
    user_notifications_status[user_id] = True  # Обновляем статус уведомлений для этого пользователя

    global notifications_started
    if not notifications_started:
        # Если это первый раз, когда пользователь включает уведомления, запускаем сразу же проверку обновлений
        notifications_started = True
        await check_updates(user_id)  # Сразу проверяем обновления

    await bot.send_message(query.message.chat.id, "Уведомления включены ✅")

@dp.callback_query_handler(lambda c: c.data == 'disable_notifications')
async def disable_notifications(query: types.CallbackQuery):
    logger.info("disable_notifications called")  
    await bot.answer_callback_query(query.id)
    user_id = query.from_user.id
    user_notifications_status[user_id] = False  # Обновляем статус уведомлений для этого пользователя
    await bot.send_message(query.message.chat.id, "Уведомления выключены ❌")






@dp.message_handler(lambda message: message.text == "Включить/Выключить уведомления 🔔")
async def handle_notification_toggle(message: types.Message):
    logger.info("handle_notification_toggle called")
    user_id = message.from_user.id
    inline_markup = types.InlineKeyboardMarkup()
    inline_markup.add(types.InlineKeyboardButton("Включить уведомления 🔔", callback_data='enable_notifications'))
    inline_markup.add(types.InlineKeyboardButton("Выключить уведомления 🔕", callback_data='disable_notifications'))
    await bot.send_message(user_id, "Выберите действие:", reply_markup=inline_markup)


@dp.message_handler()
async def handle_comment(message: types.Message):
    logger.info("handle_comment called") 
    user_id = message.from_user.id
    if user_id in user_notifications:
        issue_id = user_notifications[user_id]
        comment_text = message.text
        await send_comment(issue_id, user_id, comment_text)
        del user_notifications[user_id]



async def on_startup(dp):
    logger.info("Bot started")
    jobs['job'] = asyncio.create_task(notification_job())
    asyncio.create_task(periodic_check_projects())  # Запуск асинхронной задачи тут
    await bot.send_message(chat_id=configs.ADMIN_TELEGRAM_ID, text='🤖')



async def on_shutdown(dp):
    logger.info("Bot stopped")
    if 'job' in jobs:
        jobs['job'].cancel()
        del jobs['job']
    jobs.clear()
    await bot.send_message(chat_id=configs.ADMIN_TELEGRAM_ID, text='Bot has been stopped')



if __name__ == '__main__':
    dp.register_message_handler(start, commands=['start'])#1
    executor.start_polling(dp, on_startup=on_startup, on_shutdown=on_shutdown)
    #, on_startup=on_startup, on_shutdown=on_shutdown
    print('Bot started')