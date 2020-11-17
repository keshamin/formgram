import formgram as fg
import telebot
import calendar
import datetime


TOKEN = 'BOT_TOKEN_HERE'
bot = telebot.TeleBot(TOKEN)


def handle_submit(form: 'UserForm', callback: telebot.types.CallbackQuery):
    """
    Callback that will be invoked on successful form submission;
    This signature is mandatory
    :param form: form instance with all up-to-date field values
    :param callback: Telegram callback query object initiated by clicking Submit button
    :return: None, the return value is ignored
    """
    # In callbacks you can use bot object from Enclosing scope
    # OR use bot attribute from Form object like this:
    form.bot.send_message(callback.message.chat.id, f'Form submitted by {form.name} (@{form.username})')


class UserForm(fg.BaseForm):
    # General form configuration
    bot = bot
    submit_callback = handle_submit

    # StrField is basic Field type that stores value as is
    name = fg.StrField(label='Name', required=True)

    # You can mark any field as read_only. User doesn't have a button
    # to edit this field, but still you can edit it from the code
    username = fg.StrField(label='Username', read_only=True)

    # IntField tries to cast input value to int and rejects the value if fails to
    # Note: if you omit the 'label' argument the attribute name is used as label
    age = fg.IntField()

    # BoolField creates a simple True/False toggle-switch in form keyboard
    is_admin = fg.BoolField(label='Is Admin', required=True, initial_value=False)

    # InlineChoiceField a dropdown-like UI to choose a value from a list
    # List of possible string values must be provided in field definition
    # as a list of strings (unlike DynamicChoiceField)
    sex = fg.ChoiceField(label='Sex', choices=['M', 'F'], initial_value='M', required=True)

    # DynamicInlineChoiceField works just like ChoiceField, but choices are
    # provided in runtime for each instance of the form.
    # In this example we want user to choose a day of current month. Number of days is
    # different in different months, so we will provide appropriate choices in runtime
    # basing on current month.
    day_of_month = fg.DynamicChoiceField(label='Day of Month', required=True, row_width=7)


@bot.message_handler(commands=['form'])
def send_form(message: telebot.types.Message):
    # Create a form object and set a read-only parameter(s)
    # UserForm(username=message.from_user.username) would do the same
    form = UserForm()
    form.username = message.from_user.username

    # Prepare a list of days of current month
    now = datetime.datetime.now()
    month_days_num = calendar.monthlen(now.year, now.month)
    month_days_list = [str(n + 1) for n in range(month_days_num)]
    # Set choices for this exact
    form.fields.day_of_month.choices = month_days_list

    form.send_form(message.chat.id)


bot.polling()
