"""预下载 FastEmbed 中文向量模型，供内网离线环境部署前准备。

用法（联网机器上执行，之后把缓存目录整体拷贝到内网机器）：
    # 国内网络必须走镜像（HuggingFace 直连超时；xet 协议在镜像上 401，须禁用）：
    HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
        uv run python scripts/prefetch_embeddings.py --cache-dir D:/hf-cache

背景：知识库语义检索依赖 fastembed（BAAI/bge-small-zh-v1.5），模型在首次检索时
触发下载。内网离线会失败并导致检索报错。上线前务必先完成下载，并将缓存目录
拷贝到目标机器、设置 HF_HOME 指向它。

注意：fastembed 默认把模型缓存在系统临时目录（Windows 上重启可能被清理），
生产环境务必显式设置 HF_HOME 到持久路径。
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch the FastEmbed model for offline use.")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="模型缓存目录；默认使用环境变量 HF_HOME，未设置则用 fastembed 默认路径",
    )
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    args = parser.parse_args(argv)

    if args.cache_dir is not None:
        os.environ["HF_HOME"] = str(args.cache_dir)
    if not os.environ.get("HF_ENDPOINT") and not os.environ.get("HF_HOME"):
        print("提示：国内网络建议设 HF_ENDPOINT=https://hf-mirror.com 与 HF_HUB_DISABLE_XET=1")

    from fastembed import TextEmbedding

    print(f"正在下载/校验模型: {args.model}")
    model = TextEmbedding(model_name=args.model)
    vectors = list(model.query_embed("连通性自检"))
    print(f"模型就绪，向量维度: {len(vectors[0])}")
    cache = os.environ.get("HF_HOME", "(fastembed 默认缓存，注意可能在系统临时目录)")
    print(f"缓存位置: {cache}")
    print("内网部署：将上述缓存目录整体拷贝到目标机器，并设置同名 HF_HOME 环境变量。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
