from typing import Optional, Any, Dict, List, Tuple, Callable, Union

import telebot
from telebot import types as tb_types


# A sentinel object to detect if a parameter is supplied or not.  Use
# a class to give it a better repr.
class _MISSING_TYPE:
    pass
MISSING = _MISSING_TYPE()


FORMGRAM_PREFIX = '__extensions__/formgram'


class FormActions:
    EDIT = 'edit'
    SUBMIT = 'submit'
    CANCEL = 'cancel'


def make_form_prefix(form_name: str) -> str:
    return FORMGRAM_PREFIX + '/' + form_name


def make_edit_cb_data(form_name: str, field_name: str) -> str:
    return f'{make_form_prefix(form_name)}/{FormActions.EDIT}/{field_name}'


def make_ok_cb_data(form_name):
    return f'{make_form_prefix(form_name)}/{FormActions.SUBMIT}'


def make_cancel_cb_data(form_name):
    return f'{make_form_prefix(form_name)}/{FormActions.CANCEL}'


CANCEL_CB_DATA = f'{FORMGRAM_PREFIX}/cancel'
edit_cancel_button = tb_types.InlineKeyboardButton('Cancel', callback_data=CANCEL_CB_DATA)
edit_cancel_markup = tb_types.InlineKeyboardMarkup()
edit_cancel_markup.add(edit_cancel_button)


class Field:

    def __init__(self, type_: type, initial_value: Any = MISSING, required: bool = False,
                 label: Optional[str] = None, read_only: bool = False):
        self.type_ = type_
        self.value = initial_value
        self.required = required
        self.label = label
        self.read_only = read_only

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_value):
        if type(new_value) is not self.type_ and new_value is not MISSING:
            raise ValueError(f'Field value must be of type {self.type_}, not {type(new_value)}')
        self._value = new_value

    def __get__(self, instance, owner):
        return self.value

    def __set__(self, instance, value):
        self.value = value

    def needs_value(self):
        return self.required and self.value is MISSING

    def to_str(self, value):
        return str(value)

    def from_str(self, string):
        return self.type_(string)

    def _handle_edit(self, bot: telebot.TeleBot, form: 'BaseForm', cb: tb_types.CallbackQuery):
        sent_msg = bot.send_message(cb.message.chat.id, 'Send new value', reply_markup=edit_cancel_markup)

        def handler(msg: tb_types.Message):
            try:
                self.value = self.from_str(msg.text)
            except ValueError as e:
                bot.send_message(cb.message.chat.id, f'Invalid value, cannot cast to {self.type_}')
                return
            bot.edit_message_reply_markup(sent_msg.chat.id, sent_msg.message_id,
                                          reply_markup=tb_types.InlineKeyboardMarkup())
            bot.delete_message(cb.message.chat.id, cb.message.message_id)
            bot.send_message(cb.message.chat.id, form.to_message(), reply_markup=form.make_markup())
        bot.register_next_step_handler(cb.message, handler)


class StrField(Field):
    def __init__(self, initial_value: Any = MISSING, required: bool = False,
                 label: Optional[str] = None, read_only: bool = False):
        super().__init__(str, initial_value, required, label, read_only)

    def to_str(self, value):
        return value

    def from_str(self, string):
        return string


class BoolField(Field):
    def __init__(self, representation: Union[Dict[bool, str], Callable] = lambda: {True: '✅', False: '❌'},
                 initial_value: Any = MISSING, required: bool = False, label: Optional[str] = None,
                 read_only: bool = False):
        super().__init__(bool, initial_value, required, label, read_only)

        if callable(representation):
            representation = representation()

        self.val2repr = representation
        self.repr2val = {v: k for k, v in representation.items()}

    def to_str(self, value):
        return self.val2repr[value]

    def from_str(self, string):
        return self.repr2val[string]


def generate_init(fields_dict: Dict[str, Field]):

    def form_init(self, *args, **kwargs):
        # Merge args and kwargs into a dict
        kw = dict(zip(fields_dict, args))
        kw.update(kwargs)

        for field_name, field_obj in fields_dict.items():
            self.__dict__[field_name] = field_obj
            if field_name in kw:
                field_obj.value = kw[field_name]

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
            # Set attribute name as a field label
            if field_obj.label is None:
                field_obj.label = field_name

            class_._label_to_field[field_obj.label] = field_name

        class_._fields_dict = fields_dict

        if name != 'BaseForm':
            bot = attrs.get('_bot')
            @bot.callback_query_handler(lambda cb: cb.data.startswith(make_form_prefix(name)))
            def handler(callback):
                class_.handle_cb(class_.from_message(callback.message.text), callback)

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

    _bot: telebot.TeleBot = None
    submit_callback = None
    cancel_callback = None

    def __post_init__(self, *_, **__):
        # self._bot.callback_query_handler(
        #     lambda cb: cb.data.startswith(make_form_prefix(self.__class__.__name__)))(self.handle_cb)

        @self._bot.callback_query_handler(lambda cb: cb.data == CANCEL_CB_DATA)
        def cancel(cb):
            self._bot.delete_message(cb.message.chat.id, cb.message.message_id)
            self._bot.next_step_handlers.pop(cb.message.chat.id, None)

    def make_edit_cb_data(self, field_name):
        return make_edit_cb_data(self.__class__.__name__, field_name)

    def make_ok_cb_data(self):
        return make_ok_cb_data(self.__class__.__name__)

    def make_cancel_cb_data(self):
        return make_cancel_cb_data(self.__class__.__name__)

    def handle_cb(self, callback: tb_types.CallbackQuery):
        parts = callback.data.split('/')
        action = parts[3]
        action_to_handler = {
            FormActions.EDIT: self.handle_edit,
            FormActions.SUBMIT: self.handle_submit,
            FormActions.CANCEL: self.handle_cancel,
        }
        if action not in action_to_handler:
            self._bot.answer_callback_query(callback.id, 'Unknown callback data!')
            return
        action_to_handler[action](callback)

    def handle_edit(self, callback: tb_types.CallbackQuery):
        field_name = callback.data.split('/')[-1]
        field = self._fields_dict.get(field_name)
        if not field:
            self._bot.answer_callback_query(callback.id, 'Trying to edit unknown field!')
        field._handle_edit(self._bot, self, callback)

    def handle_submit(self, cb: tb_types.CallbackQuery):
        try:
            self.validate()
        except ValidationError as ve:
            msg = ''
            if ve.missing_fields:
                msg = 'Fill all required fields first!'
            else:
                msg = 'Validation error!'
            self._bot.answer_callback_query(cb.id, msg)
            return
        self._bot.edit_message_reply_markup(cb.message.chat.id, cb.message.message_id,
                                            reply_markup=tb_types.InlineKeyboardMarkup())
        self.submit_callback()

    def handle_cancel(self, cb: tb_types.CallbackQuery):
        self._bot.edit_message_reply_markup(cb.message.chat.id, cb.message.message_id,
                                            reply_markup=tb_types.InlineKeyboardMarkup())
        if self.cancel_callback is not None:
            self.cancel_callback()

    @property
    def fields(self) -> List[Field]:
        return list(self._fields_dict.values())

    def to_message(self) -> str:
        lines = []
        for field_name, field_options in self._fields_dict.items():
            label = field_options.label or field_name
            value = self.__dict__[field_name].value
            if value is MISSING:
                value = self.missing_value_str
            else:
                value = field_options.to_str(value)
            lines.append(f'{label}{self.separator}{value}')
        return '\n'.join(lines)

    @classmethod
    def from_message(cls, message: str, **additional_kwargs):
        kwargs = {}
        for line in message.splitlines():
            sep_idx = line.find(cls.separator)
            label, value = line[:sep_idx], line[sep_idx + len(cls.separator):]
            field_name = cls._label_to_field[label]
            if value == cls.missing_value_str:
                value = MISSING
            else:
                value = cls._fields_dict[field_name].from_str(value)
            kwargs[field_name] = value
        return cls(**kwargs, **additional_kwargs)

    def validate(self):
        missing_fields = dict(filter(
            lambda entry: entry[1].required and entry[1].value is MISSING,
            self._fields_dict.items()
        ))
        if missing_fields:
            raise ValidationError(missing_fields=missing_fields)

    def make_markup(self, custom_buttons: Optional[List[tb_types.InlineKeyboardButton]] = None):
        markup = tb_types.InlineKeyboardMarkup()
        for field_name, field in filter(lambda x: not x[1].read_only, self._fields_dict.items()):
            if field.needs_value():
                icon = '💢'
            else:
                icon = '✏️'

            markup.add(tb_types.InlineKeyboardButton(
                text=f'{icon} {field.label}',
                callback_data=self.make_edit_cb_data(field_name)
            ))

        if custom_buttons:
            markup.add(*custom_buttons)

        ok_cancel_buttons = [tb_types.InlineKeyboardButton('OK', callback_data=self.make_ok_cb_data())]
        if self.cancel_callback is not None:
            ok_cancel_buttons.append(tb_types.InlineKeyboardButton('Cancel', callback_data=self.make_cancel_cb_data()))

        markup.row(*ok_cancel_buttons)

        return markup
