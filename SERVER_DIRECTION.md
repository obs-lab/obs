# OBS Server Direction

This document describes the long-term architectural direction from a desktop
tool to a company-installable platform. It is a design and migration reference,
not a finished implementation. The current release keeps FAISS for vectors and
an in-memory graph, and this document explains how each component is meant to be
replaced without rewriting the rest of the system.

## Principle: substitutable components

OBS is built so that its heavy components sit behind narrow interfaces. The file
`backends.py` defines two abstractions:

- `VectorBackend`: add, search, reconstruct, reset, save, load, and the `ntotal`
  and `dim` properties. The current implementation is `FaissVectorBackend`,
  which wraps the existing FAISS HNSW index with no behavioural change.
- `GraphBackend`: add_node, add_edge, nodes, edges, remove_doc, load. The current
  implementation is `InMemoryGraphBackend`, which mirrors the existing in-memory
  dictionaries.

New backends implement the same interface and are selected through
`make_vector_backend` and `make_graph_backend`. Nothing above these interfaces
needs to change when a backend is swapped.

## Vector store: FAISS to Qdrant

FAISS keeps the index in process memory and persists it to a single file. Qdrant
runs as a separate service and stores vectors with payloads, which suits a
multi-user server.

Migration path:

1. Add a `QdrantVectorBackend` that implements `VectorBackend`. `add` upserts
   points with the chunk id as the point id and the chunk metadata as payload.
   `search` calls the Qdrant query API. `reconstruct` retrieves a stored vector
   by id.
2. Keep the same normalised vectors and cosine distance already used with FAISS,
   so retrieval quality is unchanged.
3. Point selection is by configuration only. The rest of the retrieval pipeline,
   reranking, clustering, and entity positioning, reads through the interface.

Clustering and entity positioning currently call `reconstruct` to rebuild
vectors from the index. A Qdrant backend must support the same call so those two
features keep working without change.

## Entity graph: in-memory to Neo4j

The entity graph is currently a set of node and edge dictionaries held in
memory and persisted to JSON. Neo4j stores the same nodes and edges as a real
graph and allows queries over paths and communities.

Migration path:

1. Add a `Neo4jGraphBackend` that implements `GraphBackend`. Nodes become graph
   nodes keyed by entity id, edges become relationships carrying the same
   attributes already stored, including the source document id and, where
   present, the typed relation and its confidence.
2. `remove_doc` deletes the relationships that came from a given document, the
   same semantics as the in-memory version.
3. The thematic communities computed on entity vectors remain a separate step,
   fed by the vector backend, so the two backends stay independent.

## Access control: already present

Role-based access control already exists in `auth.py`: three roles (developer,
admin, user), server-side enforcement through `require_roles`, per-user document
ownership, sessions with sliding expiry, lockout after repeated failures, and an
access log. The server direction does not need a new access model; it needs the
existing one to be applied to any new service boundaries introduced by Qdrant or
Neo4j, so those services are never exposed without the same checks.

## Deployment: CPU to GPU

The embedding model runs on CPU today. On a server with a GPU the same
`sentence-transformers` model loads on the GPU by passing the device at load
time, which shortens indexing time on large archives. The choice is a
configuration value; the rest of the code is unchanged because embedding is
already isolated behind `get_embed_model`.

## What is not changed now

This release does not remove FAISS or the in-memory graph. It adds the
`backends.py` abstraction so the swap can happen later, one component at a time,
against a running system. A full replacement is a separate project to be planned
on its own, because it introduces external services with their own deployment,
backup, and security concerns.
