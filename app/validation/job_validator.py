class JobValidator:

    def __init__(self, config: dict):
        self.config = config

    def validate(self, job) -> tuple[bool, str]:

        text = (
            f"{job.title} "
            f"{job.description} "
            f"{job.location}"
        ).lower()

        for excluded_term in self.config["excluded_terms"]:
            if excluded_term.lower() in text:
                return False, f"Excluded term: {excluded_term}"

        return True, ""