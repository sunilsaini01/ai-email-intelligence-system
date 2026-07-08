from dataclasses import dataclass, field
from typing import Optional
import re
import html
import logging

from bs4 import BeautifulSoup
import spacy

logger = logging.getLogger(__name__)

@dataclass
class PreprocessingConfig:
    """
    All preprocessing decisions in one place.
    Change here, affects the entire pipeline consistently.
    """
    strip_html: bool = True
    remove_quoted_replies: bool = True
    remove_signature: bool = True
    normalize_urls: bool = True
    url_token: str = "URL_TOKEN"
    lowercase: bool = True
    remove_stopwords: bool = False        # Off by default — see §2.3
    keep_negations: bool = True           # Always keep "not", "no", etc.
    lemmatize: bool = True
    min_token_length: int = 2
    max_tokens: int = 512                 # BERT context window awareness
    spacy_model: str = "en_core_web_sm"


class EmailPreprocessor:
    """
    Single, reusable preprocessing pipeline.
    One instance per process — spaCy model is expensive to load.
    Designed to be serialized and reused at inference time.
    """

    def __init__(self, config: PreprocessingConfig):
        self.config = config
        self._nlp: Optional[object] = None  # Lazy load

        if config.keep_negations:
            from nltk.corpus import stopwords
            base = set(stopwords.words("english"))
            negations = {"not","no","never","neither","nor","none","cannot",
                         "can't","won't","don't","doesn't","didn't","hasn't",
                         "haven't","isn't","aren't","wasn't","weren't"}
            self._stop_words = base - negations
        else:
            from nltk.corpus import stopwords
            self._stop_words = set(stopwords.words("english"))

    @property
    def nlp(self):
        """Lazy-load spaCy — only if lemmatization is needed."""
        if self._nlp is None and self.config.lemmatize:
            self._nlp = spacy.load(
                self.config.spacy_model,
                disable=["parser", "ner"]   # Only need tagger for lemmatization
            )
        return self._nlp

    def process(self, text: str) -> str:
        """
        Full pipeline. Returns cleaned string.
        Never raises — returns empty string on total failure.
        """
        if not text or not isinstance(text, str):
            return ""

        try:
            return self._process_internal(text)
        except Exception as e:
            logger.warning(f"Preprocessing failed: {e}")
            return ""

    def _process_internal(self, text: str) -> str:
        # 1. HTML entities and tag stripping
        if self.config.strip_html:
            text = html.unescape(text)
            soup = BeautifulSoup(text, "html.parser")
            for tag in soup(["style", "script", "head", "meta"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)

        # 2. Remove quoted replies
        if self.config.remove_quoted_replies:
            text = self._remove_quotes(text)

        # 3. Remove signature
        if self.config.remove_signature:
            text = re.split(
                r"\n--\s*\n",
                text,
                maxsplit=1
        )[0].strip()

        # 4. Normalize URLs
        if self.config.normalize_urls:
            text = re.sub(r"http[s]?://\S+", self.config.url_token, text)

        # 5. Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # 6. Lowercase
        if self.config.lowercase:
            text = text.lower()

        # 7. Lemmatize and tokenize in one pass
        if self.config.lemmatize:
            tokens = self._lemmatize_and_filter(text)
        else:
            tokens = text.split()
            tokens = [t for t in tokens if len(t) >= self.config.min_token_length]

        # 8. Remove stopwords (optional — off by default)
        if self.config.remove_stopwords:
            tokens = [t for t in tokens if t not in self._stop_words]

        # 9. Truncate to max tokens
        tokens = tokens[:self.config.max_tokens]

        return " ".join(tokens)

    def _remove_quotes(self, text: str) -> str:
        # Gmail/Apple: "On [date], [person] wrote:"
        text = re.sub(r"On .{10,200}wrote:\s*", "", text, flags=re.DOTALL)
        # Outlook original message block
        text = re.sub(
            r"(-{3,}|_{3,})\s*(Original|Forwarded) Message.*",
            "", text, flags=re.DOTALL | re.IGNORECASE
        )
        # Quoted lines (">")
        text = re.sub(r"^>.*$", "", text, flags=re.MULTILINE)
        return text.strip()

    def _lemmatize_and_filter(self, text: str) -> list[str]:
        doc = self.nlp(text)
        return [
            token.lemma_
            for token in doc
            if (
                not token.is_space
                and not token.is_punct
                and len(token.text) >= self.config.min_token_length
            )
        ]

    def process_batch(self, texts: list[str], n_process: int = 1) -> list[str]:
        """
        Batch processing — use n_process > 1 for CPU parallelism with spaCy.
        """
        return [self.process(text) for text in texts]
    
# ==========================
# Task-specific configurations
# ==========================

SPAM_CONFIG = PreprocessingConfig(
    remove_stopwords=True,
    lemmatize=True,
)

SENTIMENT_CONFIG = PreprocessingConfig(
    remove_stopwords=False,
    lemmatize=False,
)

SUMMARY_CONFIG = PreprocessingConfig(
    lowercase=False,
    remove_stopwords=False,
    lemmatize=False,
)