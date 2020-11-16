import copy
import enum
import re
from collections import Iterable
from dataclasses import dataclass
from typing import Optional, Any, Dict, List, Tuple, Callable, Union

import telebot
from telebot import types as tb_types

FORMGRAM_PREFIX = '__fg'
MISSING_VALUE_ICON = '💢'
READ_ONLY_ICON = '🔒'
EDIT_ICON = '✏️'


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
    CUSTOM_BUTTON = 'cb'
    FIELD_HANDLER = 'fh'


def make_form_prefix(form_name: str) -> str:
    return FORMGRAM_PREFIX + '/' + form_name


def make_edit_cb_data(form_name: str, field_name: str) -> str:
    return f'{make_form_prefix(form_name)}/{FormActions.EDIT.value}/{field_name}'


def make_cb_data(form_name, form_action: FormActions):
    return f'{make_form_prefix(form_name)}/{form_action.value}'


def make_custom_button_cb_data(form_name, button_idx):
    return f'{make_form_prefix(form_name)}/{FormActions.CUSTOM_BUTTON.value}/{button_idx}'


def make_field_handler_cb_data(form_name: str, field_name: str, data: str):
    return f'{make_form_prefix(form_name)}/{FormActions.FIELD_HANDLER.value}/{field_name}/{data}'


def escape_md(string: str) -> str:
    for char in '_*~[`':
        string = string.replace(char, f'\\{char}')
    return string


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

    def from_repr(self, text_value: Optional[str], meta: dict) -> 'Field':
        """
        Builds a field from text representation + metadata dict.
        :param text_value: Text representation of the field value
        :param meta: dict of field's metadata
        :return: vaopy of the field with value and all parameters set up
        """
        field_copy = copy.deepcopy(self)

        if text_value is None:
            field_copy.value = None
        else:
            field_copy.value = self.type_(text_value)
        return field_copy

    def from_str_value(self, string):
        return self.type_(string)

    def make_button(self, callback_data: str):
        icon = self.get_field_icon()
        return tb_types.InlineKeyboardButton(text=f'{icon} {self.label}', callback_data=callback_data)

    def get_field_icon(self):
        if self.read_only:
            return READ_ONLY_ICON
        if self.needs_value():
            return MISSING_VALUE_ICON
        return EDIT_ICON

    def get_meta(self) -> dict:
        return {}

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

    def custom_handler(self, form: 'BaseForm', callback: tb_types.CallbackQuery):
        pass


class StrField(Field):
    def __init__(self, initial_value: Optional[str] = None, required: bool = False,
                 label: Optional[str] = None, read_only: bool = False, noneable: bool = True):
        super().__init__(str, initial_value, required, label, read_only, noneable)

    def to_repr(self, missing_value_str: str):
        if self.value is None:
            return missing_value_str
        return escape_md(self.value)

    def from_repr(self, text_value: Optional[str], meta: dict) -> 'Field':
        field_copy = copy.deepcopy(self)
        field_copy.value = text_value
        return field_copy

class IntField(Field):
    def __init__(self, initial_value: Optional[int] = None, required: bool = False,
                 label: Optional[str] = None, read_only: bool = False, noneable: bool = True):
        super().__init__(int, initial_value, required, label, read_only, noneable)

    def from_str_value(self, string):
        try:
            return int(string)
        except ValueError as ve:
            raise ValueError(f'Cannot cast "{string}" to integer!') from ve


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

    def from_repr(self, text_value: Optional[str], meta: dict) -> 'Field':
        field_copy = copy.deepcopy(self)

        if text_value is None:
            field_copy.value = None
        else:
            field_copy.value = self.repr2val[text_value]
        return field_copy

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
        for i, choice in enumerate(self.choices):
            text = choice
            if self.value == choice:
                text = '✅ ' + text
            choice_buttons.append(tb_types.InlineKeyboardButton(
                text=text,
                callback_data=form.make_field_handler_cb_data(self.name, str(i))
            ))
        markup.add(*choice_buttons)

        markup.add(tb_types.InlineKeyboardButton(
            text='Cancel',
            callback_data=form.make_cb_data(FormActions.DISPLAY_MAIN)
        ))
        bot.edit_message_reply_markup(cb.message.chat.id, cb.message.message_id, reply_markup=markup)

    def custom_handler(self, form: 'BaseForm', callback: tb_types.CallbackQuery):
        choice_idx = int(callback.data.split('/')[4])
        self.value = self.choices[choice_idx]
        form.refresh(callback.message.chat.id, callback.message.message_id)


class DynamicChoiceField(ChoiceField):
    link_prefix = 'http://example.com/?data='
    separator = '\u080D'    # should be unique char the user would never use

    def __init__(self, row_width: int = 1, required: bool = False, label: Optional[str] = None,
                 read_only: bool = False):
        super().__init__([], row_width=row_width, initial_value=None, required=required,
                         label=label, read_only=read_only, noneable=True)

    def from_repr(self, text_value: Optional[str], meta: dict) -> 'Field':
        field_copy = copy.deepcopy(self)
        field_copy.value = text_value
        field_copy.choices = meta['choices'].split(self.separator)
        return field_copy

    def get_meta(self) -> dict:
        joined_choices = self.separator.join(self.choices)
        return {'choices': joined_choices}


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
                class_.handle_cb(class_.from_message(callback.message), callback)

            @bot.callback_query_handler(lambda cb: cb.data == CANCEL_CB_DATA)
            def cancel(cb):
                bot.delete_message(cb.message.chat.id, cb.message.message_id)
                bot.next_step_handlers.pop(cb.message.chat.id, None)

        # Custom buttons normalization
        if class_.custom_buttons is not None:
            buttons = []

            for obj in class_.custom_buttons:
                if isinstance(obj, CustomButton):
                    buttons.append([obj])
                    continue

                if not isinstance(obj, Iterable):
                    raise ValueError('Items of custon_buttons list must be either '
                                     'CustomButton\'s or Iterable[CustomButton]')

                for button in obj:
                    if not isinstance(button, CustomButton):
                        raise ValueError('Items of custon_buttons list must be either '
                                         'CustomButton\'s or Iterable[CustomButton]')
                buttons.append(obj)

            class_.custom_buttons = buttons

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
    custom_buttons: Union[List[tb_types.InlineKeyboardButton],
                          List[List[tb_types.InlineKeyboardButton]]] = []

    _meta_char = '\u2009'
    _meta_link_prefix = 'http://ke.mi/?meta='
    _meta_kv_separator = '\u0802'
    _meta_concatenator = '\u0801'

    def __post_init__(self, *_, **__):
        pass

    def make_edit_cb_data(self, field_name):
        return make_edit_cb_data(self.__class__.__name__, field_name)

    def make_cb_data(self, form_action: FormActions):
        return make_cb_data(self.__class__.__name__, form_action)

    def make_ok_cb_data(self):
        return self.make_cb_data(FormActions.SUBMIT)

    def make_cancel_cb_data(self):
        return self.make_cb_data(FormActions.CANCEL)

    def make_field_handler_cb_data(self, field_name: str, data: str):
        return make_field_handler_cb_data(self.__class__.__name__, field_name, data)

    def make_custom_button_cb_data(self, button_idx: int):
        return make_custom_button_cb_data(self.__class__.__name__, str(button_idx))

    def refresh(self, chat_id, message_id, resend=False):
        if resend:
            self.bot.delete_message(chat_id, message_id)
            self.bot.send_message(chat_id, self.to_message(), reply_markup=self.make_markup(), parse_mode='Markdown',
                                  disable_web_page_preview=True)
            return

        self.bot.edit_message_text(self.to_message(), chat_id, message_id, reply_markup=self.make_markup(),
                                   parse_mode='Markdown', disable_web_page_preview=True)

    def handle_cb(self, callback: tb_types.CallbackQuery):
        parts = callback.data.split('/')
        action = parts[2]
        action_to_handler = {
            FormActions.EDIT.value: self.handle_edit,
            FormActions.SUBMIT.value: self.handle_submit,
            FormActions.CANCEL.value: self.handle_cancel,
            FormActions.DISPLAY_MAIN.value: self.handle_display_main,
            FormActions.CUSTOM_BUTTON.value: self.handle_custom_button,
            FormActions.FIELD_HANDLER.value: self.pass_to_field_handler,
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

    def pass_to_field_handler(self, cb: tb_types.CallbackQuery):
        parts = cb.data.split('/')
        field_name = parts[3]
        field = self.fields_dict[field_name]
        field.custom_handler(form=self, callback=cb)

    def handle_custom_button(self, cb: tb_types.CallbackQuery):
        parts = cb.data.split('/')
        button_idx = int(parts[3])
        button_options = [button for button_row in self.custom_buttons for button in button_row][button_idx]

        button_options.callback(self, cb)

        if button_options.closes_form:
            self.close_form(cb.message.chat.id, cb.message.message_id)

    def pack_meta_as_link(self, meta: dict) -> str:
        meta_str = self._meta_concatenator.join([f'{k}{self._meta_kv_separator}{v}' for k, v in meta.items()])
        return f'{self._meta_link_prefix}{meta_str}'

    @classmethod
    def parse_meta_from_link(cls, link: str) -> Optional[dict]:
        meta_str = link[len(cls._meta_link_prefix):]
        if not meta_str:
            return None
        return dict(((pair.split(cls._meta_kv_separator)) for pair in meta_str.split(cls._meta_concatenator)))

    @classmethod
    def extract_href_from_line(cls, line: str) -> Optional[str]:
        href_re = r'href="(.*?)"'
        found = re.findall(href_re, line)
        if not found:
            return None
        return found[0]

    def to_message(self) -> str:
        lines = []
        for field_name, field in self.fields_dict.items():
            icon = field.get_field_icon()
            meta = field.get_meta()
            if len(meta) > 0:
                meta_container = f'[{self._meta_char}]({self.pack_meta_as_link(field.get_meta())})'
            else:
                meta_container = self._meta_char
            value = field.to_repr(missing_value_str=self.missing_value_str)
            label = escape_md(field.label)
            lines.append(f'{icon}{meta_container}{label}{self.separator}{value}')
        return '\n'.join(lines)

    @classmethod
    def from_message(cls, message: tb_types.Message, **additional_kwargs):
        kwargs = {}
        text_lines = message.text.splitlines()
        for i, (text_line, html_line) in enumerate(zip(text_lines, message.html_text.splitlines())):

            meta_char_idx = text_line.find(cls._meta_char)
            text_line = text_line[meta_char_idx + 1:]  # Cut icon and meta

            sep_idx = text_line.find(cls.separator)
            # Last line is trimmed in Telegram, so when the value is missing
            # the trailing separator with whitespaces is trimmed
            if sep_idx == -1 and i == len(text_lines) - 1:
                trimmed_separator = cls.separator.strip()
                if text_line[-1] != trimmed_separator:
                    raise ValueError(f'Cannot deserialize message {message}')
                label, value = text_line[:-1 * len(trimmed_separator)], cls.missing_value_str
            else:
                label, value = text_line[:sep_idx], text_line[sep_idx + len(cls.separator):]

            href = cls.extract_href_from_line(html_line)
            meta = None
            if href:
                meta = cls.parse_meta_from_link(href)

            field_name = cls._label_to_field[label]
            field = cls.fields_dict[field_name]

            if value == cls.missing_value_str:
                value = None

            value_or_field = field.from_repr(value, meta)
            kwargs[field_name] = value_or_field

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

        i = 0
        for button_row in self.custom_buttons:
            buttons = []
            for custom_button in button_row:
                buttons.append(tb_types.InlineKeyboardButton(
                    text=custom_button.text,
                    callback_data=self.make_custom_button_cb_data(button_idx=i)
                ))
                i += 1
            markup.row(*buttons)

        ok_cancel_buttons = [tb_types.InlineKeyboardButton('OK', callback_data=self.make_ok_cb_data())]
        if self.cancel_callback is not None:
            ok_cancel_buttons.append(tb_types.InlineKeyboardButton('Cancel', callback_data=self.make_cancel_cb_data()))

        markup.row(*ok_cancel_buttons)

        return markup

    def send_form(self, chat_id):
        self.bot.send_message(chat_id, self.to_message(), reply_markup=self.make_markup(), parse_mode='Markdown',
                              disable_web_page_preview=True)
