import os
import time
import numpy as np
import mmh3
import torch
from kiwipiepy import Kiwi
from collections import Counter
from qdrant_client import QdrantClient, models
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForFeatureExtraction
from onnxruntime import SessionOptions
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv

# .env 파일 로드 
load_dotenv()

class KNUSearcher:
    """
    KNU Hybrid Searcher implementing BGE-M3 ONNX (Dense) and Kiwi (Sparse).
    [cite_start]Synced with ingestion logic defined in embedding.txt [cite: 1-127]
    """
    def __init__(self):
        print("[System] Initializing Search Engine from Environment Variables...")
        
        # 1. 환경 변수 로드 및 검증
        self.model_path = os.getenv("MODEL_PATH", "./bge-m3-onnx-quantized")
        self.qdrant_url = os.getenv("QDRANT_URL")
        self.qdrant_api_key = os.getenv("QDRANT_API_KEY")
        self.collection_name = os.getenv("QDRANT_COLLECTION_NAME", "knu_hybrid_2026")

        # 필수 변수 검증
        if not self.qdrant_url:
            raise ValueError("❌ 환경 변수 'QDRANT_URL'이 설정되지 않았습니다. .env 파일을 확인해주세요.")

        # 2. Sparse Encoder Setup (Kiwi)
        self.kiwi = Kiwi()
        [cite_start]# [cite: 8] Stop tags from embedding.txt
        self.stop_tags = {
            'JKS', 'JKC', 'JKG', 'JKO', 'JKB', 'JKV', 'JKQ', 'JX', 'JC',
            'EP', 'EF', 'EC', 'ETN', 'ETM',
            'SP', 'SS', 'SE', 'SO', 'SL', 'SH', 'SN', 'SF', 'SY',
            'IC', 'XPN', 'XSN', 'XSV', 'XSA', 'XR', 'MM', 'MAG', 'MAJ',
            'VCP', 'VCN', 'VA', 'VV', 'VX'
        }
        
        # 3. Dense Encoder Setup (ONNX)
        print(f"[System] Loading ONNX model from: {self.model_path}")
        sess_options = SessionOptions()
        sess_options.intra_op_num_threads = 4
        
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self.model = ORTModelForFeatureExtraction.from_pretrained(
                self.model_path,
                provider="CPUExecutionProvider",
                session_options=sess_options
            )
        except Exception as e:
            print(f"[Error] Failed to load ONNX model. Check path: {e}")
            raise

        # 4. Qdrant Client Setup
        try:
            self.client = QdrantClient(
                url=self.qdrant_url,
                api_key=self.qdrant_api_key,
                port=443,
                https=True,
                timeout=60,
                # Cloudflare 터널 등 사용 시 인증서 오류 무시 필요할 수 있음
                verify=False if "cloudflare" in self.qdrant_url else True
            )
            print(f"[System] Connected to Qdrant: {self.qdrant_url} (Collection: {self.collection_name})")
        except Exception as e:
            print(f"[Error] Qdrant Connection Failed: {e}")
            raise

    def _encode_sparse(self, text: str) -> Tuple[Optional[List[int]], Optional[List[float]]]:
        """
        Generates sparse vector using Kiwi morph analysis and MMH3 hashing.
        [cite_start]Consistent with sparse_encoder logic in embedding.txt [cite: 30-45]
        """
        try:
            tokens = self.kiwi.tokenize(text)
            # Filter stop tags and short tokens
            keywords = [
                t.form for t in tokens 
                if t.tag not in self.stop_tags and len(t.form) > 1
            ]
            
            if not keywords: 
                return None, None
            
            # Count frequency (Basic BM25 approximation for query side)
            term_counts = Counter(keywords)
            
            indices = []
            values = []
            
            for term, count in term_counts.items():
                [cite_start]# [cite: 44] Hashing must match ingestion logic
                idx = mmh3.hash(term, signed=False)
                # Query-side weighting: simple sqrt or count is standard for Splade/BM25
                val = float(np.sqrt(count)) 
                
                indices.append(idx)
                values.append(val)
                
            return indices, values
        except Exception as e:
            print(f"[Warning] Sparse encoding error: {e}")
            return None, None

    def _encode_dense(self, text: str) -> List[float]:
        """
        Generates dense vector using BGE-M3 ONNX.
        """
        inputs = self.tokenizer(
            text, 
            padding=True, 
            truncation=True, 
            max_length=512, 
            return_tensors="pt"
        )
        
        outputs = self.model(**inputs)
        [cite_start]# [cite: 6] BGE-M3 uses CLS token (index 0)
        embedding = outputs.last_hidden_state[:, 0]
        
        [cite_start]# [cite: 6] Normalize (L2)
        norm = torch.norm(embedding, p=2, dim=1, keepdim=True)
        embedding = embedding.div(norm)
        
        return embedding[0].detach().numpy().tolist()

    def search(self, query: str, target_dept: str = None, final_k: int = 10):
        """
        Hybrid Search with Dept Filtering.
        Returns processed list of dicts with all metadata guaranteed.
        """
        start_time = time.perf_counter()
        
        # 1. Query Encoding
        dense_vec = self._encode_dense(query)
        sp_indices, sp_values = self._encode_sparse(query)
        encode_end_time = time.perf_counter()
        
        # 2. Build Filter
        search_filter = None
        if target_dept and target_dept != "공통": # '공통'이 아닌 경우에만 필터링
            search_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="dept",
                        match=models.MatchValue(value=target_dept)
                    )
                ]
            )

        # 3. Prefetch Setup
        # Strategy: Increase prefetch limit to 50 to improve RRF recall
        prefetch_limit = 50 
        prefetch = []
        
        # Dense Prefetch
        prefetch.append(models.Prefetch(
            query=dense_vec,
            using="dense",
            limit=prefetch_limit,
            filter=search_filter
        ))
        
        # Sparse Prefetch
        if sp_indices:
            prefetch.append(models.Prefetch(
                query=models.SparseVector(indices=sp_indices, values=sp_values),
                using="sparse",
                limit=prefetch_limit,
                filter=search_filter
            ))
            
        # 4. Execute Hybrid Search (RRF Fusion)
        try:
            results = self.client.query_points(
                collection_name=self.collection_name, # 환경변수 사용
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=final_k,
                with_payload=True, # Fetch all metadata
                with_vectors=False # Save bandwidth
            )
        except Exception as e:
            # 🚨 Error Handling: Return empty list safely
            print(f"[Error] Qdrant query failed: {e}")
            return [], {"total": 0, "encode": 0, "db": 0}, dense_vec

        end_time = time.perf_counter()
        
        # 5. Parse Results (Convert to Agent-friendly Dict)
        parsed_results = []
        if results and results.points:
            for point in results.points:
                payload = point.payload or {}
                
                # Extract essential fields safely
                item = {
                    "score": point.score,
                    "id": point.id,
                    "url": payload.get("url", "URL 없음"),
                    "title": payload.get("title", "제목 없음"),
                    "dept": payload.get("dept", "공통"),
                    "date": payload.get("date", ""),
                    "content": payload.get("content", ""), # Use this for RAG context
                    "metadata": payload # Keep full metadata just in case
                }
                parsed_results.append(item)

        latencies = {
            "total": (end_time - start_time) * 1000,
            "encode": (encode_end_time - start_time) * 1000,
            "db": (end_time - encode_end_time) * 1000
        }
        
        return parsed_results, latencies, dense_vec