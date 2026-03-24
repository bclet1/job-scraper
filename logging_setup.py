"""Shared logging configuration for quiet console output."""

import logging
import os
import warnings


def configure_logging() -> None:
    """Reduce console noise and only surface errors."""
    os.environ.setdefault('HF_HUB_DISABLE_PROGRESS_BARS', '1')
    os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')

    logging.basicConfig(
        level=logging.ERROR,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    noisy_loggers = [
        'httpx',
        'httpcore',
        'sentence_transformers',
        'transformers',
        'huggingface_hub',
        'urllib3',
    ]

    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    warnings.filterwarnings(
        'ignore',
        message='You are sending unauthenticated requests to the HF Hub.*',
    )