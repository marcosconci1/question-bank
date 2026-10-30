"""Pure functions for Brazilian public-sector IT exam (concurso) PDF ingestion.

Supports four exam boards (bancas):
- ``fgv`` (Fundação Getulio Vargas)
- ``iades`` (Instituto Americano de Desenvolvimento)
- ``cesgranrio`` (Fundação Cesgranrio)
- ``fcpc`` (Fundação Cearense de Pesquisa e Cultura)

All functions in this module are pure and offline (no network calls).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import unicodedata
from typing import Any

import pymupdf

ANNULLED = "ANNULLED"
VALID_BANCAS = ("fgv", "iades", "cesgranrio", "fcpc")
PDF_OPERATOR_PATTERNS = (
    re.compile(r"/F\d+\s+\d+(?:\.\d+)?\s+Tf\b"),
    re.compile(r"\bBT\b[\s\S]{0,80}\bET\b"),
    re.compile(r"\b\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s+Td\b"),
)


@dataclass
class ParsedCandidate:
    """A candidate question extracted from an exam booklet PDF."""

    banca: str
    number: int
    stem: str
    options: list[str]
    page: int
    raw_span: str
    section: str = ""
    gabarito_number: int | None = None
    round_trip_ok: bool = True
    quarantine_reason: str | None = None


@dataclass(frozen=True)
class TopicRule:
    """Explainable keyword/phrase rule mapping question text to registered tags."""

    name: str
    patterns: tuple[re.Pattern[str], ...]
    tags: tuple[str, ...]
    require_context: tuple[re.Pattern[str], ...] = ()


def fold_accents(text: str) -> str:
    """Lowercase and strip diacritical marks (accent-insensitive normalization)."""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return stripped.lower()


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace to a single space and strip ends."""
    cleaned = text.replace("\xad", "").replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_for_dedupe(text: str) -> str:
    """Normalize text for cross-caderno / cross-role deduplication."""
    folded = fold_accents(text.replace("\xad", ""))
    folded = re.sub(r"[^a-z0-9]+", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def normalize_for_round_trip(text: str) -> str:
    """Normalize text for round-trip comparison between JSON fields and PDF span."""
    cleaned = text.replace("\xad", "").replace("\u200b", "").replace("\ufeff", "")
    # Remove option markers like (A), (B), A), B) so stem+options match raw span
    cleaned = re.sub(r"(?:^|\s)\([A-Ea-e]\)(?=\s|$)", " ", cleaned)
    cleaned = re.sub(r"(?:^|\s)[A-Da-d]\)(?=\s|$)", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def verify_round_trip(stem: str, options: list[str], raw_span: str) -> bool:
    """Return True if re-rendered JSON text equals PDF span after whitespace normalization."""
    if not stem or not options or not raw_span:
        return False
    rendered = f"{stem} " + " ".join(options)
    return normalize_for_round_trip(rendered) == normalize_for_round_trip(raw_span)


# ---------------------------------------------------------------------------
# Per-banca page header / footer / watermark stripping
# ---------------------------------------------------------------------------

_FGV_SECTION_HEADERS = {
    "lingua portuguesa",
    "raciocinio logico e matematico",
    "raciocinio logico",
    "raciocinio logico-matematico",
    "noções de direito constitucional e administrativo",
    "nocoes de direito constitucional e administrativo",
    "direito constitucional e administrativo",
    "direito administrativo",
    "direito constitucional",
    "conhecimentos gerais",
    "conhecimentos basicos",
    "conhecimentos especificos",
    "lingua inglesa",
    "ingles",
    "estatistica",
    "legislacao",
    "etica no servico publico",
}

_CESGRANRIO_SECTION_HEADERS = {
    "conhecimentos basicos",
    "conhecimentos especificos",
    "conhecimentos gerais",
    "conhecimentos transversais",
    "lingua portuguesa",
    "lingua portuguesa i",
    "lingua portuguesa ii",
    "lingua inglesa",
    "lingua inglesa i",
    "lingua inglesa ii",
    "matematica",
    "matematica financeira",
    "atualidades do mercado financeiro",
    "probabilidade e estatistica",
    "conhecimentos bancarios",
    "tecnologia da informacao",
    "rascunho",
}


def is_cover_or_non_question_page(page_text: str, banca: str, page_index: int) -> bool:
    """Detect cover, instruction, essay (redação), or draft (rascunho) pages."""
    banca = banca.lower()
    folded = fold_accents(page_text)
    if page_index == 0:
        if banca in ("fgv", "iades", "fcpc", "cesgranrio"):
            # Page 1 is always cover/instructions in all 4 bancas
            if any(
                kw in folded
                for kw in (
                    "informacoes gerais",
                    "leia atentamente",
                    "prezado(a) candidato",
                    "prezado candidato",
                    "instrucoes",
                    "caderno de provas",
                    "cartao-resposta",
                    "cartao de respostas",
                    "folha de respostas",
                    "duracao da prova",
                )
            ):
                return True
    if banca == "cesgranrio":
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        folded_lines = [fold_accents(ln) for ln in lines]
        if any(ln == "redacao" or ln.startswith("redacao ") for ln in folded_lines[:6]):
            return True
        if len(folded_lines) <= 6 and any("rascunho" in ln for ln in folded_lines):
            return True
    return False


def strip_page_noise(page_text: str, banca: str) -> str:
    """Strip repeating per-page headers, footers, page numbers, and watermarks."""
    banca = banca.lower()
    raw_lines = page_text.replace("\xad", "").splitlines()
    cleaned_lines: list[str] = []

    if banca == "fgv":
        for line in raw_lines:
            s = line.strip()
            if not s:
                continue
            folded = fold_accents(s)
            # Remove PUA / Wingdings separator glyphs used by FGV headers
            if all(ord(ch) > 0xE000 or ch in " \t•" for ch in s):
                continue
            if re.search(r"\btipo\s+\d+\s*[-–—].*p[aá]gina\s+\d+\b", folded):
                continue
            if re.match(r"^fgv(\s+conhecimento|\s+projetos)?$", folded):
                continue
            if any(
                folded.startswith(prefix)
                for prefix in (
                    "tribunal regional federal",
                    "tribunal de justica do distrito federal",
                    "controladoria-geral da uniao",
                    "controladoria geral da uniao",
                    "empresa de tecnologia e informacoes da previdencia",
                    "concurso publico",
                    "banco do estado do espirito santo",
                    "banestes",
                )
            ):
                continue
            # Role header line in FGV typically appears right above/below FGV Conhecimento
            if (
                any(
                    folded.startswith(role_kw)
                    for role_kw in (
                        "analista judiciario",
                        "tecnico judiciario",
                        "analista de tecnologia da informacao",
                        "analista em tecnologia da informacao",
                        "auditor federal de financas e controle",
                    )
                )
                and len(s) < 110
                and not s.endswith(".")
            ):
                continue
            if folded in _FGV_SECTION_HEADERS:
                continue
            cleaned_lines.append(s)

    elif banca == "iades":
        for line in raw_lines:
            s = line.strip()
            if not s:
                continue
            folded = fold_accents(s)
            if folded in ("prova aplicada", "area livre", "concurso publico"):
                continue
            if re.match(r"^p[aá]gina\s+\d+\s*/\s*\d+$", folded):
                continue
            if re.match(r"^\d{3}\s*[-–—]\s*", s) and len(s) < 95:
                continue
            if re.match(r"^tipo\s+[“\"'‘]?[a-d][”\"'’]?$", folded):
                continue
            if any(
                 pat in folded
                for pat in (
                    "conhecimentos basicos",
                    "conhecimentos especificos",
                    "questoes de 1 a ",
                    "questoes de 21 a ",
                    "questoes de 26 a ",
                    "questoes de 31 a ",
                    "conselho federal de medicina",
                    "banco de brasilia",
                )
            ) and len(s) < 95:
                continue
            cleaned_lines.append(s)

    elif banca == "cesgranrio":
        for idx, line in enumerate(raw_lines):
            s = line.strip()
            if not s:
                continue
            folded = fold_accents(s)
            # Standalone page number at top of page
            if idx <= 3 and re.match(r"^\d{1,2}$", s):
                continue
            if folded in _CESGRANRIO_SECTION_HEADERS:
                continue
            if re.match(r"^gabarito\s+\d+$", folded):
                continue
            if re.match(r"^prova\s+[a-z0-9]+\b", folded) and len(s) < 100 and not s.endswith("."):
                continue
            if re.match(r"^cargo\s+\d+\b", folded) and len(s) < 100 and not s.endswith("."):
                continue
            if any(
                folded.startswith(prefix)
                for prefix in (
                    "banco do brasil",
                    "agente de tecnologia",
                    "banco da amazonia",
                    "tecnico cientifico",
                    "tecnico bancario",
                    "bndes",
                    "ipea",
                    "banese",
                    "eletronuclear",
                    "agerio",
                    "edital n",
                    "selecao externa",
                    "especialidade:",
                    "area de atuacao:",
                )
            ) and len(s) < 100 and not s.endswith("."):
                continue
            cleaned_lines.append(s)

    elif banca == "fcpc":
        for line in raw_lines:
            s = line.strip()
            if not s:
                continue
            folded = fold_accents(s)
            if re.match(r"^concurso\s+ufc[a]?\b", folded):
                continue
            if re.match(r"^p[aá]g\.\s*\d+\s*de\s*\d+", folded):
                continue
            if re.search(r"\b\d+\s+quest[oõ]es\b", folded) and len(s) < 80:
                continue
            if re.match(r"^prova\s+[123]\s*[-–—]", folded) and len(s) < 80:
                # Keep section marker in a canonical comment form so FCPC splitter knows section
                cleaned_lines.append(f"__FCPC_SECTION__:{folded}")
                continue
            if folded in ("lingua portuguesa", "legislacao", "conhecimentos especificos"):
                cleaned_lines.append(f"__FCPC_SECTION__:{folded}")
                continue
            if (
                any(
                    folded.startswith(prefix)
                    for prefix in (
                        "analista de tecnologia da informacao",
                        "tecnico de tecnologia da informacao",
                        "area:",
                        "edital ",
                        "cargo:",
                    )
                )
                and len(s) < 110
                and not s.endswith(".")
            ):
                continue
            cleaned_lines.append(s)
    else:
        raise ValueError(f"Unsupported banca: {banca!r}")

    return "\n".join(cleaned_lines)


# ---------------------------------------------------------------------------
# Question & Option Splitting
# ---------------------------------------------------------------------------

_VISUAL_DEPENDENCY_RE = re.compile(
    r"\b("
    r"figura\s+(a\s+seguir|abaixo|acima|\d+)"
    r"|imagem\s+(a\s+seguir|abaixo|acima|\d+)"
    r"|diagrama\s+(a\s+seguir|abaixo|acima|\d+)"
    r"|grafico\s+(a\s+seguir|abaixo|acima|\d+)"
    r"|ilustracao\s+(a\s+seguir|abaixo|acima)"
    r"|fluxograma\s+(a\s+seguir|abaixo|acima)"
    r"|observe\s+a\s+(figura|imagem|ilustracao|arvore\s+abaixo|arvore\s+a\s+seguir)"
    r"|conforme\s+(a\s+figura|a\s+imagem|o\s+diagrama|ilustrado\s+abaixo|mostrado\s+na\s+figura)"
    r")\b"
)


def _check_quarantine(
    stem: str,
    options: list[str],
    expected_option_count: int,
    raw_span: str,
) -> tuple[str | None, bool]:
    """Evaluate quality gates (a) and (d); return (quarantine_reason, round_trip_ok)."""
    if len(options) != expected_option_count:
        return f"option_count_{len(options)}_expected_{expected_option_count}", False
    if len(stem.strip()) < 15:
        return "short_stem", False
    for idx, opt in enumerate(options):
        if not opt or not opt.strip():
            return f"empty_option_{idx}", False
    combined = f"{stem}\n" + "\n".join(options)
    for pat in PDF_OPERATOR_PATTERNS:
        if pat.search(combined):
            return "pdf_operator_leak", False
    folded_combined = fold_accents(combined)
    if _VISUAL_DEPENDENCY_RE.search(folded_combined):
        return "needs_visual_asset", False
    rt_ok = verify_round_trip(stem, options, raw_span)
    if not rt_ok:
        return "round_trip_mismatch", False
    return None, True


def _parse_options_from_block(
    lines: list[str],
    banca: str,
) -> tuple[str, list[str], int]:
    """Split a single question's lines into (stem, options, expected_count)."""
    banca = banca.lower()
    expected_count = 4 if banca == "fcpc" else 5
    letters = "ABCD" if expected_count == 4 else "ABCDE"

    if banca == "fcpc":
        opt_re = re.compile(r"^([A-D])\)\s*(.*)$")
    else:
        opt_re = re.compile(r"^\(([A-E])\)\s*(.*)$")

    # Find option start line indices in sequential order A, B, C, D[, E]
    # Search from the bottom or sequentially after stem so we don't confuse (A) inside stem if any
    # Let's find all lines matching opt_re
    matches: list[tuple[int, str, str]] = []
    for idx, ln in enumerate(lines):
        m = opt_re.match(ln)
        if m:
            matches.append((idx, m.group(1), m.group(2)))

    # Try to find the last complete sequence of A, B, C, D[, E]
    chosen_indices: list[tuple[int, str, str]] = []
    a_positions = [i for i, (_, ch, _) in enumerate(matches) if ch == "A"]
    for a_pos in reversed(a_positions):
        seq: list[tuple[int, str, str]] = []
        target_idx = 0
        for m_tuple in matches[a_pos:]:
            if target_idx < len(letters) and m_tuple[1] == letters[target_idx]:
                seq.append(m_tuple)
                target_idx += 1
        if len(seq) == len(letters):
            chosen_indices = seq
            break

    if not chosen_indices:
        # Fallback: take whatever sequential prefix starting at first A was found
        if a_positions:
            a_pos = a_positions[-1]
            target_idx = 0
            for m_tuple in matches[a_pos:]:
                if target_idx < len(letters) and m_tuple[1] == letters[target_idx]:
                    chosen_indices.append(m_tuple)
                    target_idx += 1

    if not chosen_indices:
        stem = normalize_whitespace(" ".join(lines))
        return stem, [], expected_count

    first_opt_line = chosen_indices[0][0]
    stem_lines = lines[:first_opt_line]
    stem = normalize_whitespace(" ".join(stem_lines))

    options: list[str] = []
    for i, (line_idx, _letter, first_rest) in enumerate(chosen_indices):
        next_line_idx = chosen_indices[i + 1][0] if i + 1 < len(chosen_indices) else len(lines)
        opt_parts = [first_rest] if first_rest else []
        opt_parts.extend(lines[line_idx + 1 : next_line_idx])
        options.append(normalize_whitespace(" ".join(opt_parts)))

    return stem, options, expected_count


def split_questions_from_pages(
    pages: list[str],
    banca: str,
) -> list[ParsedCandidate]:
    """Split raw per-page text strings into ParsedCandidate records."""
    banca = banca.lower()
    if banca not in VALID_BANCAS:
        raise ValueError(f"Unsupported banca: {banca!r}")

    # Collect (page_num_1based, cleaned_line, section_name) across non-cover pages
    line_items: list[tuple[int, str, str]] = []
    current_section = ""

    for page_idx, page_text in enumerate(pages):
        if is_cover_or_non_question_page(page_text, banca, page_idx):
            continue
        cleaned = strip_page_noise(page_text, banca)
        for ln in cleaned.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("__FCPC_SECTION__:"):
                current_section = s.split(":", 1)[1]
                continue
            line_items.append((page_idx + 1, s, current_section))

    # Identify question boundaries
    candidates: list[ParsedCandidate] = []

    if banca == "iades":
        q_start_re = re.compile(r"^QUEST[AÃ]O\s+(\d{1,3})\b[\s_]*$", re.IGNORECASE)
        blocks: list[tuple[int, int, str, list[str]]] = []
        cur_q: int | None = None
        cur_page = 1
        cur_sec = ""
        cur_lines: list[str] = []
        for page_no, ln, sec in line_items:
            m = q_start_re.match(ln)
            if m:
                if cur_q is not None and cur_lines:
                    blocks.append((cur_q, cur_page, cur_sec, cur_lines))
                cur_q = int(m.group(1))
                cur_page = page_no
                cur_sec = sec
                cur_lines = []
            else:
                if cur_q is not None:
                    cur_lines.append(ln)
        if cur_q is not None and cur_lines:
            blocks.append((cur_q, cur_page, cur_sec, cur_lines))

    elif banca == "fcpc":
        q_start_re = re.compile(r"^(\d{2})\.\s+(.*)$")
        blocks = []
        cur_q = None
        cur_page = 1
        cur_sec = ""
        cur_lines = []

        def _has_fcpc_options(lines_so_far: list[str]) -> bool:
            has_a = any(ln.startswith("A)") for ln in lines_so_far)
            has_d = any(ln.startswith("D)") for ln in lines_so_far)
            return has_a and has_d

        for page_no, ln, sec in line_items:
            m = q_start_re.match(ln)
            if m and 1 <= int(m.group(1)) <= 60:
                n = int(m.group(1))
                if cur_q is None or _has_fcpc_options(cur_lines):
                    if cur_q is not None and cur_lines:
                        blocks.append((cur_q, cur_page, cur_sec, cur_lines))
                    cur_q = n
                    cur_page = page_no
                    cur_sec = sec
                    rest = m.group(2).strip()
                    cur_lines = [rest] if rest else []
                    continue
            if cur_q is not None:
                cur_lines.append(ln)
        if cur_q is not None and cur_lines:
            blocks.append((cur_q, cur_page, cur_sec, cur_lines))

    else:
        # FGV and Cesgranrio: standalone number line "1" .. "100"
        # Questions are strictly sequential; require cur_q + 1 <= n <= cur_q + 3 after options.
        q_num_re = re.compile(r"^(\d{1,3})$")
        blocks = []
        cur_q = None
        cur_page = 1
        cur_sec = ""
        cur_lines = []

        def _has_options_so_far(lines_so_far: list[str]) -> bool:
            has_a = any(ln.startswith("(A)") for ln in lines_so_far)
            has_e = any(ln.startswith("(E)") or ln.startswith("(D)") for ln in lines_so_far)
            return has_a and has_e

        for page_no, ln, sec in line_items:
            m = q_num_re.match(ln)
            if m:
                n = int(m.group(1))
                is_new_q = False
                if cur_q is None and 1 <= n <= 5:
                    is_new_q = True
                elif cur_q is not None and _has_options_so_far(cur_lines):
                    if n == cur_q + 1:
                        is_new_q = True
                    elif cur_q + 1 < n <= cur_q + 5 and sum(1 for l_item in cur_lines if l_item.startswith("(A)")) >= 2:
                        is_new_q = True
                if is_new_q:
                    if cur_q is not None and cur_lines:
                        blocks.append((cur_q, cur_page, cur_sec, cur_lines))
                    cur_q = n
                    cur_page = page_no
                    cur_sec = sec
                    cur_lines = []
                    continue
            if cur_q is not None:
                cur_lines.append(ln)
        if cur_q is not None and cur_lines:
            blocks.append((cur_q, cur_page, cur_sec, cur_lines))

    for q_num, page_no, sec, b_lines in blocks:
        raw_span = " ".join(b_lines)
        stem, options, expected_count = _parse_options_from_block(b_lines, banca)
        q_reason, rt_ok = _check_quarantine(stem, options, expected_count, raw_span)

        # For FCPC where Prova 1 (1..10), Prova 2 (1..10), Prova 3 (1..30) restart at 01,
        # compute the 1..50 gabarito index so it maps unambiguously to the 50-answer page.
        gab_num = q_num
        if banca == "fcpc":
            if "prova 2" in sec and q_num <= 10:
                gab_num = 10 + q_num
            elif "prova 3" in sec and q_num <= 30:
                gab_num = 20 + q_num

        candidates.append(
            ParsedCandidate(
                banca=banca,
                number=q_num,
                stem=stem,
                options=options,
                page=page_no,
                raw_span=raw_span,
                section=sec,
                gabarito_number=gab_num,
                round_trip_ok=rt_ok,
                quarantine_reason=q_reason,
            )
        )

    return candidates


def extract_questions_from_pdf(
    pdf_path: str | Path,
    banca: str,
) -> list[ParsedCandidate]:
    """Open a PDF via PyMuPDF and extract all candidate questions."""
    doc = pymupdf.open(str(pdf_path))
    try:
        pages = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return split_questions_from_pages(pages, banca)


# ---------------------------------------------------------------------------
# Answer Key (Gabarito) Parsing
# ---------------------------------------------------------------------------

def _normalize_answer_token(token: str) -> str | None:
    """Normalize an answer token to 'A'..'E' or ANNULLED, or None if not an answer token."""
    t = token.strip().upper()
    if t in ("A", "B", "C", "D", "E"):
        return t
    if t in ("*", "#", "X", "N", "NULA", "ANULADA", "ANULADO"):
        return ANNULLED
    return None


def parse_gabarito_text(pages: list[str], banca: str) -> dict[str, dict[int, str]]:
    """Parse answer key pages into {section_header_normalized: {q_num: 'A'..'E'|'ANNULLED'}}."""
    banca = banca.lower()
    sections: dict[str, dict[int, str]] = {}

    if banca == "fgv":
        # Each role/tipo block in FGV gabarito has a header containing "TIPO N"
        # followed by rows of question numbers (e.g. 1..20) and answers (A..E or *).
        full_text = "\n".join(pages)
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
        cur_header: str | None = None
        pending_Header_part = ""
        i = 0
        while i < len(lines):
            ln = lines[i]
            folded = fold_accents(ln)
            if (
                folded.startswith("pagina ")
                or "questao anulada" in folded
                or "gabarito definitivo" in folded
                or "gabaritos definitivos" in folded
                or "gabarito preliminar" in folded
                or "gabaritos preliminares" in folded
                or "concurso publico" in folded
                or "provas aplicadas" in folded
                or "gabaritos - provas" in folded
            ):
                i += 1
                continue

            # Detect header line with Tipo 1..4
            if re.search(r"\btipo\s+\d+\b", folded):
                if re.match(r"^(?:prova\s+)?tipo\s+\d+$", folded) and pending_Header_part:
                    cur_header = fold_accents(f"{pending_Header_part} - {ln}")
                else:
                    cur_header = folded
                sections.setdefault(cur_header, {})
                pending_Header_part = ""
                i += 1
                continue

            # Collect consecutive integer tokens
            if re.match(r"^\d{1,3}$", ln) and cur_header is not None:
                nums: list[int] = []
                while i < len(lines) and re.match(r"^\d{1,3}$", lines[i]):
                    nums.append(int(lines[i]))
                    i += 1
                ans_tokens: list[str] = []
                while i < len(lines) and len(ans_tokens) < len(nums):
                    norm = _normalize_answer_token(lines[i])
                    if norm is not None:
                        ans_tokens.append(norm)
                        i += 1
                    else:
                        break
                if len(nums) == len(ans_tokens):
                    for qn, ans in zip(nums, ans_tokens):
                        sections[cur_header][qn] = ans
                continue

            if not re.match(r"^\d{1,3}$", ln) and _normalize_answer_token(ln) is None:
                pending_Header_part = ln
            i += 1

    elif banca == "iades":
        full_text = "\n".join(pages)
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
        cur_role = ""
        cur_tipo = ""
        i = 0
        while i < len(lines):
            ln = lines[i]
            folded = fold_accents(ln)
            if re.match(r"^\d{3}\s*[-–—]\s*", ln):
                cur_role = folded
                cur_tipo = ""
                i += 1
                continue
            m_tipo = re.search(r"prova\s+tipo\s+[“\"'‘]?([a-d])[”\"'’]?", folded)
            if m_tipo:
                cur_tipo = f"tipo-{m_tipo.group(1)}"
                sec_key = f"{cur_role}|{cur_tipo}".strip("|")
                sections.setdefault(sec_key, {})
                i += 1
                continue
            if re.match(r"^\d{1,3}$", ln) and cur_tipo:
                sec_key = f"{cur_role}|{cur_tipo}".strip("|")
                nums = []
                while i < len(lines) and re.match(r"^\d{1,3}$", lines[i]):
                    nums.append(int(lines[i]))
                    i += 1
                ans_tokens = []
                while i < len(lines) and len(ans_tokens) < len(nums):
                    norm = _normalize_answer_token(lines[i])
                    if norm is not None:
                        ans_tokens.append(norm)
                        i += 1
                    else:
                        break
                if len(nums) == len(ans_tokens):
                    for qn, ans in zip(nums, ans_tokens):
                        sections[sec_key][qn] = ans
                continue
            i += 1

    elif banca == "fcpc":
        for page_text in pages:
            if "GABARITO OFICIAL" not in page_text.upper():
                continue
            after_header = re.split(r"GABARITO\s+OFICIAL", page_text, flags=re.IGNORECASE)[-1]
            role_part = re.split(
                r"PROVA\s+1|L[ÍI]NGUA\s+PORTUGUESA",
                after_header,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            role_key = fold_accents(normalize_whitespace(role_part))
            body_part = after_header[len(role_part) :]
            body_part = re.split(r"Fortaleza\s*,", body_part, maxsplit=1, flags=re.IGNORECASE)[0]
            body_fixed = re.sub(r"NUL\s+A", "NULA", body_part, flags=re.IGNORECASE)
            # Strip section titles before finding answer tokens so 'A' in 'LÍNGUA' or 'PROVA' isn't matched
            body_no_titles = re.sub(
                r"(?:PROVA\s+[123]\s*[-–—]\s*)?(?:L[ÍI]NGUA\s+PORTUGUESA|LEGISLA[ÇC][ÃA]O|CONHECIMENTOS\s+ESPEC[ÍI]FICOS)",
                " ",
                body_fixed,
                flags=re.IGNORECASE,
            )
            tokens = re.findall(r"\b(?:[A-D]|NULA|N)\b", body_no_titles)
            ans_map: dict[int, str] = {}
            for idx, tok in enumerate(tokens, start=1):
                norm = _normalize_answer_token(tok)
                if norm is not None:
                    ans_map[idx] = norm
            if ans_map:
                sections[role_key] = ans_map

    elif banca == "cesgranrio":
        # Handle both standard sequential "1 - A" pages and BNDES multi-column "Prova 1..6" pages
        shared_basic: dict[int, str] = {}
        full_lines: list[str] = []
        for page_idx, page_text in enumerate(pages):
            p_lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
            p_folded = [fold_accents(ln) for ln in p_lines]
            # Check if this page is a BNDES-style multi-column table with Prova 1..6 or Prova 7..13
            prova_cols = [ln for ln in p_folded if re.match(r"^prova\s+\d+$", ln)]
            if len(prova_cols) >= 4:
                for col in prova_cols:
                    sections.setdefault(col, dict(shared_basic))
                # Extract all "<num> - <ans>" pairs in order on this page
                joined = "\n".join(p_lines)
                pairs = re.findall(
                    r"(\d{1,3})\s*-\s*(Anulada|ANULADA|[A-E])\b",
                    joined,
                    flags=re.IGNORECASE,
                )
                # Group pairs by question number
                by_q: dict[int, list[str]] = {}
                for q_str, ans_str in pairs:
                    by_q.setdefault(int(q_str), []).append(_normalize_answer_token(ans_str) or ANNULLED)
                for qn, ans_list in by_q.items():
                    if len(ans_list) == len(prova_cols):
                        for col, ans in zip(prova_cols, ans_list):
                            sections[col][qn] = ans
                continue

            full_lines.extend(p_lines)

        # Standard sequential parser across full_lines
        joined_all = "\n".join(full_lines)
        # Normalize split "1 -\nB" into "1 - B"
        joined_all = re.sub(
            r"(\d{1,3})\s*-\s*\n\s*(Anulada|ANULADA|[A-E])\b",
            r"\1 - \2",
            joined_all,
            flags=re.IGNORECASE,
        )
        cur_sec = "default"
        sections.setdefault(cur_sec, {})
        for ln in joined_all.splitlines():
            s = ln.strip()
            if not s:
                continue
            folded = fold_accents(s)
            # Check for section headers
            if (
                re.match(r"^gabarito\s+\d+$", folded)
                or re.match(r"^prova\s+[a-z0-9]+\b", folded)
                or ("tecnico bancario" in folded and "gabarito" in folded)
                or ("tecnico cientifico" in folded and "formacao" in folded)
                or ("conhecimentos basicos" in folded and "provas de" in folded)
                or "conhecimentos gerais" == folded
            ) and not re.match(r"^\d{1,3}\s*-", folded):
                cur_sec = folded
                sections.setdefault(cur_sec, dict(shared_basic))
                continue

            m_pair = re.match(r"^(\d{1,3})\s*-\s*(Anulada|ANULADA|[A-E])\b", s, flags=re.IGNORECASE)
            if m_pair:
                qn = int(m_pair.group(1))
                ans = _normalize_answer_token(m_pair.group(2)) or ANNULLED
                sections[cur_sec][qn] = ans
                if cur_sec in ("default", "conhecimentos gerais") or "conhecimentos basicos" in cur_sec:
                    shared_basic[qn] = ans
                    # Also propagate shared basic answers to already-created prova sections
                    for k, sec_dict in sections.items():
                        if k != cur_sec and qn not in sec_dict:
                            sec_dict[qn] = ans

    else:
        raise ValueError(f"Unsupported banca: {banca!r}")

    return {k: v for k, v in sections.items() if v}


def parse_gabarito_pdf(pdf_path: str | Path, banca: str) -> dict[str, dict[int, str]]:
    """Open an answer key PDF via PyMuPDF and parse all role/caderno answer maps."""
    doc = pymupdf.open(str(pdf_path))
    try:
        pages = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return parse_gabarito_text(pages, banca)


def match_gabarito_section(
    sections: dict[str, dict[int, str]],
    banca: str,
    role: str,
    caderno: str,
    organ: str = "",
) -> dict[int, str] | None:
    """Match a manifest prova's (role, caderno) to the parsed gabarito section."""
    if not sections:
        return None
    banca = banca.lower()
    role_f = fold_accents(role)
    cad_f = fold_accents(caderno).replace("-", " ")

    if banca == "iades":
        # Match by tipo-a .. tipo-d and role code 102 (Analista de TI)
        target_tipo = fold_accents(caderno)
        candidates = [
            (k, v)
            for k, v in sections.items()
            if target_tipo in k and ("tecnologia da informacao" in k or "102" in k or len(sections) <= 4)
        ]
        if candidates:
            return candidates[0][1]

    elif banca == "fcpc":
        # Match by normalized role/area words
        role_words = set(re.findall(r"[a-z0-9]+", role_f))
        best_key = None
        best_score = -1.0
        for k, v in sections.items():
            k_words = set(re.findall(r"[a-z0-9]+", k))
            if not k_words:
                continue
            overlap = len(role_words & k_words) / max(len(role_words), len(k_words))
            # Check key area terms (back, front, dados, governanca, infraestrutura, seguranca, multimidia, suporte, ui)
            area_part = role_f.split("area:")[-1] if "area:" in role_f else role_f
            area_words = set(re.findall(r"[a-z0-9]+", area_part)) - {"de", "da", "do", "em", "e", "ti", "sistemas", "desenvolvimento", "software"}
            if area_words and area_words.issubset(k_words):
                overlap += 1.0
            if overlap > best_score:
                best_score = overlap
                best_key = k
        if best_key is not None and best_score >= 0.5:
            return sections[best_key]

    elif banca == "fgv":
        # Clean role: strip "(Tipo 1)" suffix from role name if present
        role_clean = re.sub(r"\s*\(tipo\s*\d+\)\s*", "", role_f).strip()
        # Extract tipo number from caderno ("tipo-1" -> "tipo 1")
        m_tipo = re.search(r"tipo\s*(\d+)", cad_f)
        tipo_num = m_tipo.group(1) if m_tipo else "1"
        tipo_re = re.compile(rf"\btipo\s+{tipo_num}\b")

        # Score candidate headers that have matching tipo_num
        best_key = None
        best_score = -1.0
        # Normalize abbreviations in role_clean
        role_expanded = (
            role_clean.replace("analista de ti", "analista de tecnologia da informacao")
            .replace("analista em ti", "analista em tecnologia da informacao")
            .replace("suporte em ti", "suporte em tecnologia da informacao")
            .replace("gestao de ti", "gestao de tecnologia da informacao")
        )
        r_tokens = set(re.findall(r"[a-z0-9]+", role_expanded)) - {"de", "da", "do", "em", "e", "area", "apoio", "especializado", "tipo", "prova"}
        for k, v in sections.items():
            if not tipo_re.search(k):
                continue
            k_tokens = set(re.findall(r"[a-z0-9]+", k)) - {"de", "da", "do", "em", "e", "area", "apoio", "especializado", "tipo", "prova", "1", "2", "3", "4"}
            if not k_tokens:
                continue
            # Require level match (analista vs tecnico vs auditor)
            for lvl in ("analista", "tecnico", "auditor"):
                if (lvl in r_tokens) != (lvl in k_tokens):
                    break
            else:
                inter = len(r_tokens & k_tokens)
                union = len(r_tokens | k_tokens)
                score = inter / union if union else 0.0
                if r_tokens.issubset(k_tokens) or k_tokens.issubset(r_tokens):
                    score += 0.5
                if score > best_score:
                    best_score = score
                    best_key = k
        if best_key is not None and best_score >= 0.45:
            return sections[best_key]

    elif banca == "cesgranrio":
        # Match by caderno (e.g., "gabarito-1" -> "gabarito 1", "prova-8" -> "prova 8", "cargo-16" -> "prova 16")
        cad_norm = cad_f.replace("cargo ", "prova ")
        for k, v in sections.items():
            if k == cad_norm or k.startswith(cad_norm + " ") or k.startswith(cad_norm + " -") or k.startswith(cad_norm + " –"):
                # Verify it's not a mismatched role (like basa 2022 tecnico bancario vs tecnico cientifico)
                if "tecnico bancario" in k and "tecnico cientifico" in role_f:
                    continue
                return v
        # Match by substring or role
        for k, v in sections.items():
            if cad_norm in k:
                if "tecnico bancario" in k and "tecnico cientifico" in role_f:
                    continue
                return v
        for k, v in sections.items():
            if "tecnologia da informacao" in k and "tecnologia da informacao" in role_f:
                return v
            if "tecnico cientifico" in k and "tecnico cientifico" in role_f:
                return v
        if len(sections) == 1 and "default" in sections:
            return sections["default"]

    return None


# ---------------------------------------------------------------------------
# Explainable Rule-Based Topic Classifier
# ---------------------------------------------------------------------------

_IT_CONTEXT_RE = re.compile(
    r"\b("
    r"algoritmo\w*|estrutura\w*\s+de\s+dados|banco\w*\s+de\s+dados|sgbd|sql|SELECT|tabela\w*"
    r"|chave\w*|registro\w*|ponteiro\w*|no\b|nos\b|nodo\w*|vertice\w*|aresta\w*"
    r"|vetor\w*|array\w*|busca|pesquisa|insercao|remocao|complexidade|memoria"
    r"|indice\w*|arvore\w*|hash\w*|grafo\w*|pilha\w*|fila\w*|lista\w*|heap\w*|ordenacao"
    r")\b",
    re.IGNORECASE,
)

TOPIC_RULES: tuple[TopicRule, ...] = (
    TopicRule(
        name="b_plus_tree",
        patterns=(
            re.compile(r"\barvores?\s+b\s*\+"),
            re.compile(r"\bb\s*\+\s*-?\s*trees?\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "arvores-e-suas-generalizacoes-arvores-binarias-arvores-de-busca-e-arvores-balanceadas",
            "arvore-b",
            "arvore-b-mais",
        ),
    ),
    TopicRule(
        name="b_tree",
        patterns=(
            re.compile(r"\barvores?\s+b\b(?!\s*\+)"),
            re.compile(r"\bb\s*-\s*trees?\b"),
            re.compile(r"\barvores?\s+b\s*\*" ),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "arvores-e-suas-generalizacoes-arvores-binarias-arvores-de-busca-e-arvores-balanceadas",
            "arvore-b",
        ),
    ),
    TopicRule(
        name="avl_tree",
        patterns=(
            re.compile(r"\barvores?\s+avl\b"),
            re.compile(r"\bavl\b.*\b(arvore\w*|balancead\w*|fator\s+de\s+balanceamento|rotac\w*)"),
            re.compile(r"\bfator\s+de\s+balanceamento\b.*\barvore\w*"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "arvores-e-suas-generalizacoes-arvores-binarias-arvores-de-busca-e-arvores-balanceadas",
            "arvore-avl",
        ),
    ),
    TopicRule(
        name="red_black_tree",
        patterns=(
            re.compile(r"\barvores?\s+rubro\s*-?\s*negras?\b"),
            re.compile(r"\barvores?\s+vermelho\s*-?\s*pretas?\b"),
            re.compile(r"\bred\s*-\s*black\s+trees?\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "arvores-e-suas-generalizacoes-arvores-binarias-arvores-de-busca-e-arvores-balanceadas",
            "arvore-rubro-negra",
        ),
    ),
    TopicRule(
        name="binary_and_balanced_trees",
        patterns=(
            re.compile(r"\barvores?\s+binarias?\b"),
            re.compile(r"\barvores?\s+de\s+busca\b"),
            re.compile(r"\barvores?\s+balanceadas?\b"),
            re.compile(r"\bpercurso\s+(em\s+ordem|pre\s*-?\s*ordem|pos\s*-?\s*ordem|in\s*-?\s*order|pre\s*-?\s*order|pos\s*-?\s*order)\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "arvores-e-suas-generalizacoes-arvores-binarias-arvores-de-busca-e-arvores-balanceadas",
        ),
    ),
    TopicRule(
        name="hash_chaining",
        patterns=(
            re.compile(r"\b(hash\w*|dispersao|espalhamento)\b[\s\S]{0,160}\b(encadeamento|listas?\s+encadeadas?|chaining)\b"),
            re.compile(r"\b(tratamento\s+de\s+colis\w*|colis\w*)\b[\s\S]{0,120}\bencadeamento\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "tabelas-hash",
            "hash-encadeamento",
        ),
    ),
    TopicRule(
        name="hash_open_addressing",
        patterns=(
            re.compile(
                r"\b(hash\w*|dispersao|espalhamento|colis\w*)\b[\s\S]{0,160}\b(enderecamento\s+aberto|sondagem\s+linear|sondagem\s+quadratica|duplo\s+hash\w*|open\s+addressing|linear\s+probing)\b"
            ),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "tabelas-hash",
            "hash-enderecamento-aberto",
        ),
    ),
    TopicRule(
        name="hash_table",
        patterns=(
            re.compile(r"\btabelas?\s+(de\s+)?(hash\w*|dispersao|espalhamento)\b"),
            re.compile(r"\bfunc(ao|oes)\s+(de\s+)?(hash\w*|dispersao|espalhamento)\b"),
            re.compile(r"\bhash\s+table\w*\b"),
            re.compile(r"\b(hash\w*|dispersao)\b[\s\S]{0,120}\b(colis(ao|oes)|fator\s+de\s+carga|bucket\w*)\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "tabelas-hash",
        ),
    ),
    TopicRule(
        name="database_indexes",
        patterns=(
            re.compile(r"\bindices?\s+(clusterizad\w*|agrupad\w*|primari\w*|secundari\w*|denso\w*|esparso\w*|bitmap|hash|invertid\w*|b\s*-?\s*tree|arvore\s+b)\b"),
            re.compile(r"\bcreate\s+(unique\s+|bitmap\s+)?index\b"),
            re.compile(r"\b(indexacao|estrutura\s+de\s+indice\w*|tipo\s+de\s+indice|indices?)\b[\s\S]{0,180}\b(consulta\w*\s+por\s+intervalo|range\s+quer\w*|arvore\s+b\s*\+?|b\s*-?\s*tree|bitmap|sgbd|tabela\w*\s+de\s+clientes|clausula\s+where)\b"),
        ),
        tags=(
            "tecnologia-de-computacao",
            "banco-de-dados",
            "indices-banco-de-dados",
        ),
    ),
    TopicRule(
        name="heap_priority_queue",
        patterns=(
            re.compile(r"\b(max\s*-?\s*heap|min\s*-?\s*heap|heap\s+binari\w*|heapsort|heap\s+sort)\b"),
            re.compile(r"\bfilas?\s+de\s+prioridades?\b"),
            re.compile(r"\bheap\b[\s\S]{0,100}\b(arvore\w*|prioridade\w*|ordenac\w*|complexidade|inserc\w*|remoc\w*)\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "heap-fila-de-prioridade",
        ),
    ),
    TopicRule(
        name="linear_data_structures",
        patterns=(
            re.compile(r"\blistas?\s+(simplesmente\s+|duplamente\s+)?encadeadas?\b"),
            re.compile(r"\b(pilhas?\s+e\s+filas?|filas?\s+e\s+pilhas?|lifo|fifo)\b[\s\S]{0,120}\b(estrutura\w*\s+de\s+dados|desempilh\w*|empilh\w*|enfileir\w*|ponteiro\w*|topo|no\b|nos\b)\b"),
            re.compile(r"\b(empilhar|desempilhar|push\s+e\s+pop)\b[\s\S]{0,100}\bpilha\w*\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "estruturas-de-dados-lineares-e-suas-generalizacoes-listas-ordenadas-listas-encadeadas-pilhas-e-filas",
        ),
    ),
    TopicRule(
        name="sorting_and_binary_search",
        patterns=(
            re.compile(r"\b(quicksort|quick\s+sort|mergesort|merge\s+sort|bubblesort|bubble\s+sort|insertionsort|insertion\s+sort|selectionsort|selection\s+sort|shellsort|radix\s*sort|counting\s*sort)\b"),
            re.compile(r"\b(busca\s+binaria|pesquisa\s+binaria|binary\s+search)\b"),
            re.compile(r"\balgoritmos?\s+de\s+ordenacao\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "algoritmos-para-pesquisa-e-ordenacao",
        ),
    ),
    TopicRule(
        name="graphs",
        patterns=(
            re.compile(r"\b(busca\s+em\s+largura|busca\s+em\s+profundidade|breadth\s*-?\s*first|depth\s*-?\s*first)\b"),
            re.compile(r"\balgoritmo\s+de\s+(dijkstra|bellman\s*-?\s*ford|floyd\s*-?\s*warshall|kruskal|prim)\b"),
            re.compile(r"\barvores?\s+geradoras?\s+minimas?\b"),
            re.compile(r"\bordenacao\s+topologica\b"),
            re.compile(r"\bgrafos?\s+(direcionad\w*|orientad\w*|ponderad\w*|aciclic\w*|conexo\w*|bipartid\w*)\b"),
            re.compile(r"\b(matriz\s+de\s+adjacencia\w*|lista\s+de\s+adjacencia\w*)\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "algoritmos-em-grafos",
        ),
    ),
    TopicRule(
        name="asymptotic_complexity",
        patterns=(
            re.compile(r"\b(complexidade\s+assintotica|analise\s+assintotica|complexidade\s+de\s+tempo|complexidade\s+temporal|notacao\s+big\s*-?\s*o)\b"),
            re.compile(r"\bo\s*\(\s*(?:n\s*(?:log|\*)\s*n|log\s*n|n\s*\^\s*2|n2|2\s*\^\s*n)\s*\)\b"),
        ),
        tags=(
            "fundamentos-da-computacao",
            "algoritmos-e-estrutura-de-dados",
            "medidas-de-complexidade-analise-assintotica-de-limites-de-complexidade-tecnicas-de-prova-de-cotas-inferiores",
            "notacao-big-o-little-o-omega-e-theta",
        ),
    ),
)

# Guard against cryptography-only SHA/MD5 questions matching hash_table unless they also mention
# data-structure / database concepts (tabela hash, colisão em tabela, encadeamento, sondagem, bucket, índice).
_CRYPTO_ONLY_RE = re.compile(
    r"\b(sha\s*-?\s*(?:1|256|384|512)|md5|hmac|assinatura\s+digital|certificado\s+digital|icp\s*-?\s*brasil|criptograf\w*)\b"
)
_HASH_DS_RE = re.compile(
    r"\b(tabelas?\s+(?:de\s+)?hash\w*|tabelas?\s+de\s+dispersao|encadeamento|enderecamento\s+aberto|sondagem|fator\s+de\s+carga|bucket\w*|armazenamento\s+de\s+informac\w*|estrutura\w*\s+de\s+dados|indice\w*)\b"
)


def classify_question(stem: str, options: list[str]) -> tuple[list[str], list[str]]:
    """Classify a question using explainable keyword/phrase rules on stem + options.

    Returns ``(sorted_tags, matched_rule_names)``. If ``matched_rule_names`` is empty,
    the question is out of scope for the target topics.
    """
    combined = f"{stem}\n" + "\n".join(options)
    folded = fold_accents(combined)

    if not _IT_CONTEXT_RE.search(folded):
        return [], []

    is_crypto = bool(_CRYPTO_ONLY_RE.search(folded)) and not bool(_HASH_DS_RE.search(folded))

    matched_tags: set[str] = set()
    matched_rules: list[str] = []

    for rule in TOPIC_RULES:
        if is_crypto and rule.name in ("hash_table", "hash_chaining", "hash_open_addressing"):
            continue
        if any(pat.search(folded) for pat in rule.patterns):
            matched_rules.append(rule.name)
            matched_tags.update(rule.tags)

    # Sub-refine graph subtopics when graphs rule matched
    if "graphs" in matched_rules:
        if re.search(r"\b(busca\s+em\s+largura|busca\s+em\s+profundidade|breadth\s*-?\s*first|depth\s*-?\s*first)\b", folded):
            matched_tags.add("busca-em-largura-e-profundidade")
        if re.search(r"\b(kruskal|prim|arvores?\s+geradoras?)\b", folded):
            matched_tags.add("arvore-geradora")
        if re.search(r"\b(dijkstra|bellman\s*-?\s*ford|floyd\s*-?\s*warshall|menor\s+caminho|caminho\s+minimo)\b", folded):
            matched_tags.add("algoritmos-do-menor-caminho")
        if re.search(r"\bordenacao\s+topologica\b", folded):
            matched_tags.add("ordenacao-topologica")

    # If a database index question also mentions B-tree or B+ tree, include arvore-b / arvore-b-mais
    if "database_indexes" in matched_rules and ("b_tree" in matched_rules or "b_plus_tree" in matched_rules):
        matched_tags.add("organizacao-de-arquivos-e-dados")

    return sorted(matched_tags), matched_rules


# ---------------------------------------------------------------------------
# Cross-caderno / Cross-role Deduplication
# ---------------------------------------------------------------------------

def question_fingerprint(stem: str, options: list[str]) -> str:
    """Compute an order-independent fingerprint of normalized stem + sorted options."""
    norm_stem = normalize_for_dedupe(stem)
    norm_opts = sorted(normalize_for_dedupe(opt) for opt in options)
    return f"{norm_stem}||" + "|".join(norm_opts)


def deduplicate_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate identical questions across cadernos/roles of the same (exam, organ, year).

    Preserves the first canonical record's ``id``, ``number``, ``options``, and ``answer``
    (in canonical order: sorted by ``(caderno, role, number)``), and merges ``roles``,
    ``cadernos``, ``sources``, and ``occurrences`` in ``provenance``.
    """
    grouped: dict[tuple[str, str, int, str], list[dict[str, Any]]] = {}
    for rec in records:
        prov = rec.get("provenance") or {}
        key = (
            rec["exam"],
            str(prov.get("organ", "")),
            int(rec["year"]),
            question_fingerprint(rec["stem"], rec.get("options") or []),
        )
        grouped.setdefault(key, []).append(rec)

    deduped: list[dict[str, Any]] = []
    for _key, group in grouped.items():
        # Sort deterministically so canonical record is always stable
        group.sort(
            key=lambda r: (
                str((r.get("provenance") or {}).get("caderno", "")),
                str((r.get("provenance") or {}).get("role", "")),
                int(r["number"]),
            )
        )
        canonical = dict(group[0])
        c_prov = dict(canonical.get("provenance") or {})

        roles: list[str] = []
        cadernos: list[str] = []
        occurrences: list[dict[str, Any]] = []
        seen_sources: set[tuple[str, str, str]] = set()
        merged_sources: list[dict[str, str]] = []

        for item in group:
            iprov = item.get("provenance") or {}
            r_list = iprov.get("roles") or ([iprov["role"]] if iprov.get("role") else [])
            for r in r_list:
                if r not in roles:
                    roles.append(r)
            c_list = iprov.get("cadernos") or ([iprov["caderno"]] if iprov.get("caderno") else [])
            for c in c_list:
                if c not in cadernos:
                    cadernos.append(c)

            occ_list = iprov.get("occurrences") or [
                {
                    "role": iprov.get("role", ""),
                    "caderno": iprov.get("caderno", ""),
                    "number": item["number"],
                    "answer": item.get("answer"),
                }
            ]
            for occ in occ_list:
                if occ not in occurrences:
                    occurrences.append(occ)

            for src in iprov.get("sources") or []:
                s_key = (src.get("kind", ""), src.get("url", ""), src.get("sha256", ""))
                if s_key not in seen_sources:
                    seen_sources.add(s_key)
                    merged_sources.append(src)

        c_prov["role"] = roles[0] if roles else c_prov.get("role", "")
        c_prov["roles"] = roles
        c_prov["caderno"] = cadernos[0] if cadernos else c_prov.get("caderno", "")
        c_prov["cadernos"] = cadernos
        c_prov["occurrences"] = occurrences
        c_prov["sources"] = merged_sources
        canonical["provenance"] = c_prov
        deduped.append(canonical)

    deduped.sort(key=lambda r: str(r["id"]))
    return deduped
