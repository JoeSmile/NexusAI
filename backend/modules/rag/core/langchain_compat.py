#!/usr/bin/env python3
"""
LangChain 兼容层
Chroma 已移除；向量检索改用 pgvector。
文档加载器等在缺依赖时降级为 None，避免阻断应用启动。
"""

try:
    from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, TextLoader
except ImportError:  # pragma: no cover
    PyPDFLoader = DirectoryLoader = TextLoader = None

try:
    from langchain_openai import OpenAIEmbeddings
except ImportError:  # pragma: no cover
    OpenAIEmbeddings = None

try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        RecursiveCharacterTextSplitter = None

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from dataclasses import dataclass, field

    @dataclass
    class Document:
        page_content: str = ""
        metadata: dict = field(default_factory=dict)

try:
    import langchain
    LANGCHAIN_VERSION = langchain.__version__
except (ImportError, AttributeError):
    LANGCHAIN_VERSION = "unknown"

IS_NEW_VERSION = True
Chroma = None

__all__ = [
    "IS_NEW_VERSION",
    "LANGCHAIN_VERSION",
    "Chroma",
    "DirectoryLoader",
    "Document",
    "OpenAIEmbeddings",
    "PyPDFLoader",
    "RecursiveCharacterTextSplitter",
    "TextLoader",
]
