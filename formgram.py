import copy
import enum
import re
from collections import Iterable
from dataclasses import dataclass
from typing import Optional, Any, Dict, List, Tuple, Callable, Union
from urllib.parse import urlparse

import telebot
from telebot import types as tb_types


FORMGRAM_PREFIX = '__ext__/fg'
MISSING_VALUE_SYMBOL = '💢'
EDIT_SYMBOL = '✏️'


@dataclass
class CustomButton:
    text: str
    callback: Callable[['BaseForm', tb_types.CallbackQuery], None]
    closes_form: bool


class FormActions(enum.Enum):
    EDIT = 'ed'
    SUBMIT = 'ok'
    CANCEL = 'ca'
    DISPLAY_MAIN = 'dm'
    INLINE_EDIT = 'ie'
    CUSTOM_BUTTON = 'cb'


def make_form_prefix(form_name: str) -> str:
    return FORMGRAM_PREFIX + '/' + form_name


def make_edit_cb_data(form_name: str, field_name: str) -> str:
    return f'{make_form_prefix(form_name)}/{FormActions.EDIT.value}/{field_name}'


def make_inline_edit_cb_data(form_name: str, field_name: str, value: str) -> str:
    return f'{make_form_prefix(form_name)}/{FormActions.INLINE_EDIT.value}/{field_name}/{value}'


def make_cb_data(form_name, form_action: FormActions):
    return f'{make_form_prefix(form_name)}/{form_action.value}'


def make_custom_button_cb_data(form_name, button_text):
    return f'{make_form_prefix(form_name)}/{FormActions.CUSTOM_BUTTON.value}/{button_text}'


CANCEL_CB_DATA = f'{FORMGRAM_PREFIX}/cancel'
edit_cancel_button = tb_types.InlineKeyboardButton('Cancel', callback_data=CANCEL_CB_DATA)
edit_cancel_markup = tb_types.InlineKeyboardMarkup()
edit_cancel_markup.add(edit_cancel_button)


class Field:

    def __init__(self, type_: type, initial_value: Any = None, required: bool = False,
                 label: Optional[str] = None, read_only: bool = False, noneable: bool = True):
        if initial_value is None and not noneable:
            raise ValueError('Initial value is not provided for field that isn\'t None-able.')

        self.name = None
        self.type_ = type_
        self.noneable = noneable
        self.value = initial_value
        self.required = required
        self.label = label
        self.read_only = read_only

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_value):
        if new_value is None and not self.noneable:
            raise ValueError('New value is None, but the field is not None-able')

        if type(new_value) not in (self.type_, type(None)):
            raise ValueError(f'Field value must be of type {self.type_}, not {type(new_value)}')

        self.validate_input(new_value)

        self._value = new_value

    def __get__(self, instance, type_=None):
        return instance.fields_dict[self.name].value

    def __set__(self, instance, value):
        instance.fields_dict[self.name].value = value

    def validate_input(self, new_value):
        pass

    def needs_value(self):
        return self.required and self.value is None

    def to_repr(self, missing_value_str: str):
        if self.value is None:
            return missing_value_str
        return str(self.value)

    def from_repr(self, string, missing_value_str: str):
        if string == missing_value_str:
            return None, None
        return self.type_(string), None

    def from_str_value(self, string):
        return self.type_(string)

    def from_metadata(self, metadata: dict) -> 'Field':
        """Create a copy of field and recover metadata from provided dict
        """
        field_copy = copy.deepcopy(self)
        return field_copy

    def make_button(self, callback_data: str):
        if self.needs_value():
            icon = MISSING_VALUE_SYMBOL
        else:
            icon = EDIT_SYMBOL

        return tb_types.InlineKeyboardButton(text=f'{icon} {self.label}', callback_data=callback_data)

    def _handle_edit(self, bot: telebot.TeleBot, form: 'BaseForm', cb: tb_types.CallbackQuery):
        sent_msg = bot.send_message(cb.message.chat.id, 'Send new value', reply_markup=edit_cancel_markup)

        def handler(msg: tb_types.Message):
            bot.edit_message_reply_markup(sent_msg.chat.id, sent_msg.message_id,
                                          reply_markup=tb_types.InlineKeyboardMarkup())
            try:
                self.value = self.from_str_value(msg.text)
            except ValueError as e:
                bot.send_message(cb.message.chat.id, str(e))
                return
            form.refresh(cb.message.chat.id, cb.message.message_id, resend=True)
        bot.register_next_step_handler(cb.message, handler)


class StrField(Field):
    def __init__(self, initial_value: Optional[str] = None, required: bool = False,
                 label: Optional[str] = None, read_only: bool = False, noneable: bool = True):
        super().__init__(str, initial_value, required, label, read_only, noneable)

    def to_repr(self, missing_value_str: str):
        if self.value is None:
            return missing_value_str
        return self.value

    def from_repr(self, string, missing_value_str: str):
        if string == missing_value_str:
            return None, None
        return string, None


class LinkField(StrField):
    html_link_re = r'<a.*?>(.*?)</a>'

    def from_repr(self, string, missing_value_str: str):
        found = re.findall(self.html_link_re, string)
        if len(found) == 0:
            return None, None
        found = found[0]
        if found == missing_value_str:
            return None, None
        return found, None

    def validate_input(self, new_value):
        url = urlparse(new_value)
        if '' not in (url.scheme, url.netloc):
            return
        raise ValueError(f'Link is not found in {new_value}')


class IntField(Field):
    def __init__(self, initial_value: Optional[int] = None, required: bool = False,
                 label: Optional[str] = None, read_only: bool = False, noneable: bool = True):
        super().__init__(int, initial_value, required, label, read_only, noneable)


class BoolField(Field):
    def __init__(self, representation: Union[Dict[bool, str], Callable] = lambda: {True: '✅', False: '❌'},
                 initial_value: Optional[bool] = None, required: bool = False, label: Optional[str] = None,
                 read_only: bool = False, noneable: bool = True):
        super().__init__(bool, initial_value, required, label, read_only, noneable)

        if callable(representation):
            representation = representation()

        self.val2repr = representation
        self.repr2val = {v: k for k, v in representation.items()}

    def to_repr(self, missing_value_str: str):
        if self.value is None:
            return missing_value_str
        return self.val2repr[self.value]

    def from_repr(self, string, missing_value_str: str):
        if string == missing_value_str:
            return None, None
        return self.repr2val[string], None

    def _handle_edit(self, bot: telebot.TeleBot, form: 'BaseForm', cb: tb_types.CallbackQuery):
        self.value = not self.value
        form.refresh(cb.message.chat.id, cb.message.message_id)

    def make_button(self, callback_data: str):
        if self.needs_value():
            icon = '💢'
        else:
            icon = self.val2repr[self.value]

        return tb_types.InlineKeyboardButton(text=f'{icon} {self.label}', callback_data=callback_data)


class ChoiceField(Field):
    def __init__(self, choices: Union[List[str], Callable], row_width: int = 1, initial_value: Optional[str] = None,
                 required: bool = False, label: Optional[str] = None, read_only: bool = False, noneable: bool = True):

        if callable(choices):
            choices = choices()

        if initial_value is not None and initial_value not in choices:
            raise ValueError('Initial value must be one of choices when provided!')

        self.choices = choices
        self.row_width = row_width

        super().__init__(str, initial_value, required, label, read_only, noneable)

    def _handle_edit(self, bot: telebot.TeleBot, form: 'BaseForm', cb: tb_types.CallbackQuery):
        markup = tb_types.InlineKeyboardMarkup(row_width=self.row_width)
        choice_buttons = []
        for choice in self.choices:
            text = choice
            if self.value == choice:
                text = '✅ ' + text
            choice_buttons.append(tb_types.InlineKeyboardButton(
                text=text,
                callback_data=form.make_inline_edit_cb_data(self.name, choice)
            ))
        markup.add(*choice_buttons)

        markup.add(tb_types.InlineKeyboardButton(
            text='Cancel',
            callback_data=form.make_cb_data(FormActions.DISPLAY_MAIN)
        ))
        bot.edit_message_reply_markup(cb.message.chat.id, cb.message.message_id, reply_markup=markup)


class DynamicChoiceField(ChoiceField):
    link_prefix = 'http://example.com/?data='
    separator = '&&&'

    def __init__(self, row_width: int = 1, required: bool = False, label: Optional[str] = None,
                 read_only: bool = False):
        super().__init__([], row_width=row_width, initial_value=None, required=required,
                         label=label, read_only=read_only, noneable=True)

    def to_repr(self, missing_value_str: str):
        value = self.value if self.value is not None else ''
        joined_choices = self.separator.join(self.choices)

        return f'{value}[\u2009]({self.link_prefix}{joined_choices})'

    def from_repr(self, string: str, missing_value_str: str):
        a_idx = string.rfind('<a href=')
        value = string[:a_idx]
        if value == missing_value_str:
            value = None
        href = string.split('"')[1]
        choices = href[len(self.link_prefix):].split(self.separator)
        return value, {'value': value, 'choices': choices}

    def from_metadata(self, metadata: dict) -> 'DynamicChoiceField':
        field_copy = copy.deepcopy(self)
        field_copy.value = metadata['value']
        field_copy.choices = metadata['choices']
        return field_copy


def generate_init(fields_dict: Dict[str, Field]):

    def form_init(self, *args, **kwargs):
        # Merge args and kwargs into a dict
        kw = dict(zip(fields_dict, args))
        kw.update(kwargs)

        self.fields_dict = {}

        for field_name, field_obj in fields_dict.items():
            provided = kw.get(field_name)
            if isinstance(provided, Field):
                field_obj = provided
            else:
                field_obj = copy.deepcopy(field_obj)
                if field_name in kw:
                    field_obj.value = kw[field_name]
            self.__dict__[field_name] = field_obj
            self.fields_dict[field_name] = field_obj

        if hasattr(self, '__post_init__'):
            self.__post_init__(**kwargs)

    return form_init


def generate_repr(class_name, fields_dict: Dict[str, Field]):
    def class_repr(self):
        params = (f'{field}={repr(self.__dict__[field].value)}' for field in fields_dict)
        return f'{class_name}({", ".join(params)})'

    return class_repr


class FormMeta(type):
    def __new__(mcs, name, bases, attrs):
        class_ = super().__new__(mcs, name, bases, attrs)

        fields_filter = filter(lambda name_and_value: isinstance(name_and_value[1], Field), attrs.items())
        fields_list: List[Tuple[str, Field]] = list(fields_filter)
        fields_dict: Dict[str, Field] = dict(fields_list)

        class_.__init__ = generate_init(fields_dict)
        class_.__repr__ = generate_repr(class_name=name, fields_dict=fields_dict)

        class_._label_to_field = {}
        for field_name, field_obj in fields_dict.items():
            # Set attribute name as a field label if label is not provided
            if field_obj.label is None:
                field_obj.label = field_name

            # Set attribute name as a field name
            field_obj.name = field_name

            class_._label_to_field[field_obj.label] = field_name

        class_.fields_dict = fields_dict

        if name != 'BaseForm':
            bot = attrs.get('bot')

            @bot.callback_query_handler(lambda cb: cb.data.startswith(make_form_prefix(name)))
            def handler(callback):
                class_.handle_cb(class_.from_message(callback.message.html_text), callback)

            @bot.callback_query_handler(lambda cb: cb.data == CANCEL_CB_DATA)
            def cancel(cb):
                bot.delete_message(cb.message.chat.id, cb.message.message_id)
                bot.next_step_handlers.pop(cb.message.chat.id, None)

        # Custom buttons normalization
        if class_.custom_buttons is not None:
            buttons = []
            buttons_dict = {}

            for obj in class_.custom_buttons:
                if isinstance(obj, CustomButton):
                    buttons.append([obj])
                    buttons_dict[obj.text] = obj
                    continue

                if not isinstance(obj, Iterable):
                    raise ValueError('Items of custon_buttons list must be either '
                                     'CustomButton\'s or Iterable[CustomButton]')

                buttons.append(obj)
                for button in obj:
                    if not isinstance(button, CustomButton):
                        raise ValueError('Items of custon_buttons list must be either '
                                         'CustomButton\'s or Iterable[CustomButton]')
                    buttons_dict[button.text] = button

            class_.custom_buttons = buttons
            class_.custom_buttons_dict = buttons_dict

        return class_


class ValidationError(Exception):
    def __init__(self, *args, missing_fields: Optional[dict] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.missing_fields = missing_fields

    def __str__(self):
        m = ''
        if self.missing_fields:
            m += f'Missing fields: {", ".join(self.missing_fields)}'
        return m


class BaseForm(metaclass=FormMeta):
    separator = ': '
    missing_value_str = ''

    bot: telebot.TeleBot = None
    submit_callback = None
    cancel_callback = None
    custom_buttons: List[tb_types.InlineKeyboardButton] = []

    def __post_init__(self, *_, **__):
        pass

    def make_edit_cb_data(self, field_name):
        return make_edit_cb_data(self.__class__.__name__, field_name)

    def make_cb_data(self, form_action: FormActions):
        return make_cb_data(self.__class__.__name__, form_action)

    def make_inline_edit_cb_data(self, field_name: str, value: str) -> str:
        return make_inline_edit_cb_data(self.__class__.__name__, field_name, value)

    def make_ok_cb_data(self):
        return self.make_cb_data(FormActions.SUBMIT)

    def make_cancel_cb_data(self):
        return self.make_cb_data(FormActions.CANCEL)

    def make_custom_button_cb_data(self, button_text: str):
        return make_custom_button_cb_data(self.__class__.__name__, button_text)

    def refresh(self, chat_id, message_id, resend=False):
        if resend:
            self.bot.delete_message(chat_id, message_id)
            self.bot.send_message(chat_id, self.to_message(), reply_markup=self.make_markup(), parse_mode='Markdown')
            return

        self.bot.edit_message_text(self.to_message(), chat_id, message_id, reply_markup=self.make_markup(),
                                   parse_mode='Markdown')

    def handle_cb(self, callback: tb_types.CallbackQuery):
        parts = callback.data.split('/')
        action = parts[3]
        action_to_handler = {
            FormActions.EDIT.value: self.handle_edit,
            FormActions.SUBMIT.value: self.handle_submit,
            FormActions.CANCEL.value: self.handle_cancel,
            FormActions.DISPLAY_MAIN.value: self.handle_display_main,
            FormActions.INLINE_EDIT.value: self.hanlde_inline_edit,
            FormActions.CUSTOM_BUTTON.value: self.handle_custom_button,
        }
        if action not in action_to_handler:
            self.bot.answer_callback_query(callback.id, 'Unknown callback data!')
            return
        action_to_handler[action](callback)

    def handle_edit(self, callback: tb_types.CallbackQuery):
        field_name = callback.data.split('/')[-1]
        field = self.fields_dict.get(field_name)
        if not field:
            self.bot.answer_callback_query(callback.id, 'Trying to edit unknown field!')
        field._handle_edit(self.bot, self, callback)

    def handle_submit(self, cb: tb_types.CallbackQuery):
        try:
            self.validate()
        except ValidationError as ve:
            if ve.missing_fields:
                msg = 'Fill all required fields first!'
            else:
                msg = 'Validation error!'
            self.bot.answer_callback_query(cb.id, msg)
            return

        self.close_form(cb.message.chat.id, cb.message.message_id)
        self.submit_callback(cb)

    def handle_cancel(self, cb: tb_types.CallbackQuery):
        self.close_form(cb.message.chat.id, cb.message.message_id)

        if self.cancel_callback is not None:
            self.cancel_callback(cb)

    def handle_display_main(self, cb: tb_types.CallbackQuery):
        self.refresh(cb.message.chat.id, cb.message.message_id)

    def hanlde_inline_edit(self, cb: tb_types.CallbackQuery):
        parts = cb.data.split('/')
        field_name = parts[4]
        new_value = '/'.join(parts[5:])
        field = self.fields_dict[field_name]
        try:
            field.value = field.from_str_value(new_value)
        except ValueError:
            self.bot.answer_callback_query(cb.id, 'Invalid value provided!')
            return
        self.refresh(cb.message.chat.id, cb.message.message_id)

    def handle_custom_button(self, cb: tb_types.CallbackQuery):
        parts = cb.data.split('/')
        button_text = '/'.join(parts[4:])
        button_options = self.custom_buttons_dict[button_text]

        button_options.callback(self, cb)

        if button_options.closes_form:
            self.close_form(cb.message.chat.id, cb.message.message_id)

    @property
    def fields(self) -> List[Field]:
        return list(self.fields_dict.values())

    def to_message(self) -> str:
        lines = []
        for field_name, field_options in self.fields_dict.items():
            value = field_options.to_repr(missing_value_str=self.missing_value_str)
            lines.append(f'{field_options.label}{self.separator}{value}')
        return '\n'.join(lines)

    @classmethod
    def from_message(cls, message: str, **additional_kwargs):
        kwargs = {}
        lines = message.splitlines()
        for i, line in enumerate(lines):
            sep_idx = line.find(cls.separator)
            # Last line is trimmed in Telegram, so when the value is missing
            # the trailing separator with whitespaces is trimmed
            if sep_idx == -1 and i == len(lines) - 1:
                trimmed_separator = cls.separator.strip()
                if line[-1] != trimmed_separator:
                    raise ValueError(f'Cannot deserialize message {message}')
                label, value = line[:-1 * len(trimmed_separator)], cls.missing_value_str
            else:
                label, value = line[:sep_idx], line[sep_idx + len(cls.separator):]
            field_name = cls._label_to_field[label]
            field = cls.fields_dict[field_name]

            value, metadata = field.from_repr(value, missing_value_str=cls.missing_value_str)

            if not metadata:
                kwargs[field_name] = value
                continue

            field = field.from_metadata(metadata)
            kwargs[field_name] = field

        return cls(**kwargs, **additional_kwargs)

    def close_form(self, chat_id, message_id):
        self.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=tb_types.InlineKeyboardMarkup())

    def validate(self):
        missing_fields = dict(filter(
            lambda entry: entry[1].required and entry[1].value is None,
            self.fields_dict.items()
        ))
        if missing_fields:
            raise ValidationError(missing_fields=missing_fields)

    def make_markup(self):
        markup = tb_types.InlineKeyboardMarkup()
        for field_name, field in filter(lambda x: not x[1].read_only, self.fields_dict.items()):
            markup.add(field.make_button(self.make_edit_cb_data(field_name)))

        for button_row in self.custom_buttons:
            buttons = []
            for custom_button in button_row:
                buttons.append(tb_types.InlineKeyboardButton(
                    text=custom_button.text,
                    callback_data=self.make_custom_button_cb_data(custom_button.text)
                ))
            markup.row(*buttons)

        ok_cancel_buttons = [tb_types.InlineKeyboardButton('OK', callback_data=self.make_ok_cb_data())]
        if self.cancel_callback is not None:
            ok_cancel_buttons.append(tb_types.InlineKeyboardButton('Cancel', callback_data=self.make_cancel_cb_data()))

        markup.row(*ok_cancel_buttons)

        return markup

    def send_form(self, chat_id):
        self.bot.send_message(chat_id, self.to_message(), reply_markup=self.make_markup(), parse_mode='Markdown')
