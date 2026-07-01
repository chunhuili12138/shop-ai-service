"""
文档解析器 — 支持 PDF/Excel/Word/DOC/CSV
所有函数统一接受 bytes 参数，避免临时文件问题。
每个函数内部有 try/except 保护，解析失败时抛出 ParseError。
"""

import io
import olefile
import re
from charset_normalizer import from_bytes
import clevercsv


class ParseError(Exception):
    pass


def parse_pdf_bytes(data: bytes) -> str:
    import fitz
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        texts = []
        for page in doc:
            texts.append(page.get_text())
        doc.close()
        return "\n\n".join(texts).strip()
    except Exception as e:
        raise ParseError(f"PDF 解析失败: {str(e)}")


def parse_excel_bytes(data: bytes) -> str:
    from python_calamine import CalamineWorkbook
    try:
        wb = CalamineWorkbook.from_filelike(io.BytesIO(data))
        parts = []
        sheet_names = wb.sheet_names
        for sheet_name in sheet_names:
            rows = wb.get_sheet_by_name(sheet_name).to_python()
            rows = [[c if c is not None else "" for c in row] for row in rows]
            if not rows:
                continue
            max_cols = min(len(rows[0]), 50) if rows else 0
            if max_cols == 0:
                continue

            if len(sheet_names) > 1:
                parts.append(f"## {sheet_name}\n")

            header = [str(c) if c != "" else "—" for c in rows[0][:max_cols]]
            parts.append("| " + " | ".join(header) + " |")
            parts.append("| " + " | ".join(["---"] * max_cols) + " |")

            for row in rows[1:]:
                cells = [str(c) if c != "" else "—" for c in row[:max_cols]]
                parts.append("| " + " | ".join(cells) + " |")
            parts.append("")

        return "\n".join(parts).strip()
    except Exception as e:
        raise ParseError(f"Excel 解析失败: {str(e)}")


def parse_word_bytes(data: bytes) -> str:
    import mammoth
    try:
        result = mammoth.convert_to_markdown(io.BytesIO(data))
        return result.value.strip()
    except Exception as e:
        raise ParseError(f"Word 解析失败: {str(e)}")


def parse_doc_bytes(data: bytes) -> str:
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
        text_parts = []

        if ole.exists("WordDocument"):
            raw = ole.openstream("WordDocument").read()
            try:
                text = raw.decode("utf-16-le", errors="ignore")
            except Exception:
                text = raw.decode("latin-1", errors="ignore")
            cleaned = re.sub(r"[^\x20-\x7e\u4e00-\u9fff\u3000-\u303f\uff00-\uffef\n\r\t]", "", text)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
            if cleaned.strip():
                text_parts.append(cleaned.strip())

        ole.close()

        if not text_parts:
            raise ParseError("无法从 .doc 文件中提取文本")

        return "\n\n".join(text_parts)
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"DOC 解析失败: {str(e)}")


def parse_csv_bytes(data: bytes) -> str:
    try:
        detected = from_bytes(data).best()
        text = str(detected) if detected else data.decode("utf-8", errors="replace")

        dialect = clevercsv.Sniffer().sniff(text[:5000])
        reader = clevercsv.reader(io.StringIO(text), dialect)
        rows = list(reader)
        if not rows:
            raise ParseError("CSV 文件为空")

        max_cols = min(len(rows[0]), 50)

        parts = []
        header = rows[0][:max_cols]
        parts.append("| " + " | ".join(header) + " |")
        parts.append("| " + " | ".join(["---"] * len(header)) + " |")

        for row in rows[1:]:
            cells = [c if c else "—" for c in row[:max_cols]]
            parts.append("| " + " | ".join(cells) + " |")

        return "\n".join(parts).strip()
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"CSV 解析失败: {str(e)}")


def parse_document(file_name: str, data: bytes) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    parsers = {
        "pdf": parse_pdf_bytes,
        "xlsx": parse_excel_bytes,
        "xls": parse_excel_bytes,
        "docx": parse_word_bytes,
        "doc": parse_doc_bytes,
        "csv": parse_csv_bytes,
    }

    parser = parsers.get(ext)
    if not parser:
        raise ParseError(f"不支持的文件类型: {ext}")

    return parser(data)
