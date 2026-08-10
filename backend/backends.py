from abc import ABC, abstractmethod
from typing import List, Optional, Tuple
import numpy as np


class VectorBackend(ABC):
    @abstractmethod
    def add(self, vectors: np.ndarray) -> None:
        ...

    @abstractmethod
    def search(self, query: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
        ...

    @abstractmethod
    def reconstruct(self, position: int) -> np.ndarray:
        ...

    @abstractmethod
    def reset(self, dim: int) -> None:
        ...

    @property
    @abstractmethod
    def ntotal(self) -> int:
        ...

    @property
    @abstractmethod
    def dim(self) -> int:
        ...

    @abstractmethod
    def save(self, path: str) -> None:
        ...

    @abstractmethod
    def load(self, path: str) -> bool:
        ...


class FaissVectorBackend(VectorBackend):
    def __init__(self, dim: int, hnsw_neighbors: int = 32,
                 ef_construction: int = 200, ef_search: int = 64):
        import faiss
        self._faiss = faiss
        self._dim = dim
        self._hnsw_neighbors = hnsw_neighbors
        self._ef_construction = ef_construction
        self._ef_search = ef_search
        self._index = self._new_index(dim)

    def _new_index(self, dim: int):
        index = self._faiss.IndexHNSWFlat(dim, self._hnsw_neighbors)
        index.hnsw.efConstruction = self._ef_construction
        index.hnsw.efSearch = self._ef_search
        return index

    def add(self, vectors: np.ndarray) -> None:
        self._index.add(vectors)

    def search(self, query: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
        return self._index.search(query, k)

    def reconstruct(self, position: int) -> np.ndarray:
        return self._index.reconstruct(position)

    def reset(self, dim: int) -> None:
        self._dim = dim
        self._index = self._new_index(dim)

    @property
    def ntotal(self) -> int:
        return self._index.ntotal

    @property
    def dim(self) -> int:
        return self._index.d

    def save(self, path: str) -> None:
        self._faiss.write_index(self._index, path)

    def load(self, path: str) -> bool:
        loaded = self._faiss.read_index(path)
        if loaded.d != self._dim:
            return False
        self._index = loaded
        return True

    @property
    def raw_index(self):
        return self._index

    @raw_index.setter
    def raw_index(self, index):
        self._index = index


class GraphBackend(ABC):
    @abstractmethod
    def add_node(self, node_id: str, attributes: dict) -> None:
        ...

    @abstractmethod
    def add_edge(self, edge: dict) -> None:
        ...

    @abstractmethod
    def nodes(self) -> dict:
        ...

    @abstractmethod
    def edges(self) -> List[dict]:
        ...

    @abstractmethod
    def remove_doc(self, doc_id: str) -> None:
        ...

    @abstractmethod
    def load(self, nodes: dict, edges: List[dict]) -> None:
        ...


class InMemoryGraphBackend(GraphBackend):
    def __init__(self):
        self._nodes = {}
        self._edges = []

    def add_node(self, node_id: str, attributes: dict) -> None:
        if node_id not in self._nodes:
            self._nodes[node_id] = attributes

    def add_edge(self, edge: dict) -> None:
        if edge not in self._edges:
            self._edges.append(edge)

    def nodes(self) -> dict:
        return self._nodes

    def edges(self) -> List[dict]:
        return self._edges

    def remove_doc(self, doc_id: str) -> None:
        self._edges = [e for e in self._edges if e.get("doc_id") != doc_id]

    def load(self, nodes: dict, edges: List[dict]) -> None:
        self._nodes = nodes or {}
        self._edges = edges or []


def make_vector_backend(kind: str, dim: int) -> VectorBackend:
    if kind == "faiss":
        return FaissVectorBackend(dim)
    raise ValueError("Backend vettoriale non supportato: " + str(kind))


def make_graph_backend(kind: str) -> GraphBackend:
    if kind == "memory":
        return InMemoryGraphBackend()
    raise ValueError("Backend grafo non supportato: " + str(kind))
