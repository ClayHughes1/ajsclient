from abc import ABC, abstractmethod

from app.models.job import Job


class JobSource(ABC):

    @abstractmethod
    def search(self, search_term: str) -> list[Job]:
        """Search the source and return job postings."""
        raise NotImplementedError