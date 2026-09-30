from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class PedidoAtualizarNome(_message.Message):
    __slots__ = ("user_id", "novo_nome")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    NOVO_NOME_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    novo_nome: str
    def __init__(self, user_id: _Optional[str] = ..., novo_nome: _Optional[str] = ...) -> None: ...

class EnvioChat(_message.Message):
    __slots__ = ("de_user_id", "para_user_id", "texto")
    DE_USER_ID_FIELD_NUMBER: _ClassVar[int]
    PARA_USER_ID_FIELD_NUMBER: _ClassVar[int]
    TEXTO_FIELD_NUMBER: _ClassVar[int]
    de_user_id: str
    para_user_id: str
    texto: str
    def __init__(self, de_user_id: _Optional[str] = ..., para_user_id: _Optional[str] = ..., texto: _Optional[str] = ...) -> None: ...

class MensagemChat(_message.Message):
    __slots__ = ("id", "de_user_id", "de_nome", "para_user_id", "texto", "enviada_em")
    ID_FIELD_NUMBER: _ClassVar[int]
    DE_USER_ID_FIELD_NUMBER: _ClassVar[int]
    DE_NOME_FIELD_NUMBER: _ClassVar[int]
    PARA_USER_ID_FIELD_NUMBER: _ClassVar[int]
    TEXTO_FIELD_NUMBER: _ClassVar[int]
    ENVIADA_EM_FIELD_NUMBER: _ClassVar[int]
    id: int
    de_user_id: str
    de_nome: str
    para_user_id: str
    texto: str
    enviada_em: str
    def __init__(self, id: _Optional[int] = ..., de_user_id: _Optional[str] = ..., de_nome: _Optional[str] = ..., para_user_id: _Optional[str] = ..., texto: _Optional[str] = ..., enviada_em: _Optional[str] = ...) -> None: ...

class PedidoListarConversas(_message.Message):
    __slots__ = ("user_id",)
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    def __init__(self, user_id: _Optional[str] = ...) -> None: ...

class Conversa(_message.Message):
    __slots__ = ("outro_user_id", "outro_nome", "ultima_mensagem", "ultima_em")
    OUTRO_USER_ID_FIELD_NUMBER: _ClassVar[int]
    OUTRO_NOME_FIELD_NUMBER: _ClassVar[int]
    ULTIMA_MENSAGEM_FIELD_NUMBER: _ClassVar[int]
    ULTIMA_EM_FIELD_NUMBER: _ClassVar[int]
    outro_user_id: str
    outro_nome: str
    ultima_mensagem: str
    ultima_em: str
    def __init__(self, outro_user_id: _Optional[str] = ..., outro_nome: _Optional[str] = ..., ultima_mensagem: _Optional[str] = ..., ultima_em: _Optional[str] = ...) -> None: ...

class Confirmacao(_message.Message):
    __slots__ = ("mensagem",)
    MENSAGEM_FIELD_NUMBER: _ClassVar[int]
    mensagem: str
    def __init__(self, mensagem: _Optional[str] = ...) -> None: ...
