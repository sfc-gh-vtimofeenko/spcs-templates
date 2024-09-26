import os
from dataclasses import dataclass
from typing import List

import torch
from transformers import AutoTokenizer, AutoModel, pipeline
from utils import init_logger

logger = init_logger("FeatureExtractor")

model_cache_dir = f'/tmp/model_cache/'
os.makedirs(model_cache_dir, exist_ok=True)


@dataclass
class ModelConfiguration:
    """
    Defines the model configuration
    """
    model_name: int
    tokenizer_name: str


@dataclass
class InputRow:
    """
    Defines the input format of each row
    """
    idx: int
    text: str


@dataclass
class OutputRow:
    """
    Defines the output format of each row
    """
    idx: int
    embeddings: str


embedding_pipeline = None


def extract_embeddings(rows: List[InputRow], batch_size: int, model_config: ModelConfiguration) -> List[OutputRow]:
    """
    Main function that uses model and tokenizer to produce text embeddings
    :param rows: List of input rows
    :param batch_size: Batch size that will be used by the hf pipeline
    :param model_config: model and tokenizer config
    :return: List of embeddings
    """
    texts = [row.text for row in rows]
    global embedding_pipeline
    if embedding_pipeline is None:
        embedding_pipeline = _create_embedding_pipeline(_get_cuda_device(), batch_size, model_config)
    result = _execute_inference(embedding_pipeline, texts)
    return [OutputRow(idx=rows[idx].idx, embeddings=result['outputs'][idx]) for idx in range(len(result['outputs']))]


def _create_embedding_pipeline(device: int, batch_size: int, model_config: ModelConfiguration):
    num_gpus = torch.cuda.device_count()
    logger.info(f"Creating embedding pipeline on worker: {os.getpid()}, available gpus: {num_gpus}")
    tokenizer = AutoTokenizer.from_pretrained(model_config.tokenizer_name, padding=True, truncation=True,
                                              return_tensors='pt', model_max_length=4096, cache_dir=model_cache_dir,
                                              force_download=False)
    model = AutoModel.from_pretrained(model_config.model_name, trust_remote_code=True, rotary_scaling_factor=2,
                                      cache_dir=model_cache_dir, force_download=False)
    # use fp16
    model = model.half()

    embedding_pipeline = pipeline(
        "feature-extraction",
        model=model,
        tokenizer=tokenizer,
        device=torch.device(f"cuda:{device}" if torch.cuda.is_available() else "cpu"),
        batch_size=batch_size,
    )
    return embedding_pipeline


def _get_cuda_device() -> int:
    """
    Each job instance has isolated GPU that always starts with 0
    :return: the cuda device that will be used
    """
    return 0


def _generate_embedding_sync(embedding_pipeline, input_texts: list):
    result = _execute_inference(embedding_pipeline, input_texts)
    return result['outputs']


def _execute_inference(embedding_pipeline, input_batch: list):
    results = dict(inputs=[], outputs=[], index=0)
    embeddings = embedding_pipeline(input_batch, truncation=True)
    outputs = [' '.join(map(str, embedding[0][0])) for embedding in embeddings]
    results["inputs"].extend(input_batch)
    results["outputs"].extend(outputs)
    results["index"] = 0
    return results