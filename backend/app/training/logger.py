import logging


def get_logger(
    name: str = "Email Intelligence",
):
    """
    Create and return a configured logger.
    """

    logger = logging.getLogger(name)

    if not logger.handlers:

        logger.setLevel(logging.INFO)

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)

        logger.addHandler(console_handler)

    return logger