import os
import sys
import shutil
import glob
import gc

from langchain.text_splitter import CharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

from tart.TART.src.modeling_enc_t5 import EncT5ForSequenceClassification
from tart.TART.src.tokenization_enc_t5 import EncT5Tokenizer
import torch
import torch.nn.functional as F
import numpy as np

from generation import generate_with_loop

from sentence_transformers import SentenceTransformer

# from generation import generate_with_loop

database_path = "vectorDB_0000"

def set_vector_db(chunk_size, embedding_model):
    revise_paragraph_dir = 'data'
    file_names = glob.glob(revise_paragraph_dir + "/*.txt")
    
    texts = []
    
    for file_name in file_names:
        with open(file_name, 'r') as fr:
            content = fr.read()
            paragraphs = content.split("\n")

            for paragraph in paragraphs:
                if len(paragraph) > 0:
                    texts.append(paragraph)

            fr.close()

    text_splitter = CharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=40)

    chunks = text_splitter.create_documents(texts)
    print(len(chunks))
    print(chunks[0])

    embeddings_model = HuggingFaceEmbeddings(
        model_name = embedding_model,
        model_kwargs = {'device': 'cuda'},
        encode_kwargs = {'normalize_embeddings': False}
    )
    
    if os.path.isdir(database_path):
        shutil.rmtree(database_path)
        
    os.makedirs(database_path)

    chromadb = Chroma.from_documents(chunks, 
                                     embedding=embeddings_model,
                                     collection_name='coll_cosine',
                                     collection_metadata={"hnsw:space": "cosine"},
                                     persist_directory=database_path)
    chromadb.persist()
    
    return len(chunks)

def retrieve(user_query, num, embedding_model):
    print(user_query)
    print()
    
    embeddings_model = HuggingFaceEmbeddings(
        model_name = embedding_model,
        model_kwargs = {'device': 'cuda'},
        encode_kwargs = {'normalize_embeddings': False}
    )
    
    chromadb = Chroma(embedding_function=embeddings_model,
                      collection_name='coll_cosine',
                      collection_metadata={"hnsw:space": "cosine"},
                      persist_directory=database_path)

    results = chromadb.similarity_search_with_score(user_query, num)
    
    unique_results = set()
    final_results = []

    for i in range(len(results)):
        content = results[i][0].page_content
        if content not in unique_results:
            unique_results.add(content)
            final_results.append((content, results[i][1]))
    
    final_results.sort(key=lambda a: a[1])
    
    print("number of unique results : {}".format(len(unique_results)))
    print("=======================")
    print()
    
    if len(final_results) < 10:
        first_num = len(final_results)
    else:
        first_num = 10

    total_score = 0

    for i in range(first_num):
        total_score = total_score + final_results[i][1]
    
    avrg_score = total_score / first_num
    
    return avrg_score

def retrieve_with_re_ranker(user_query, num, embedding_model, model, tokenizer, query_no):
    embeddings_model = HuggingFaceEmbeddings(
        model_name = embedding_model,
        model_kwargs = {'device': 'cuda'},
        encode_kwargs = {'normalize_embeddings': False}
    )
    
    chromadb = Chroma(embedding_function=embeddings_model,
                      collection_name='coll_cosine',
                      collection_metadata={"hnsw:space": "cosine"},
                      persist_directory=database_path)

    results = chromadb.similarity_search_with_score(user_query, num)
    
    unique_results = set()

    for i in range(len(results)):
        content = results[i][0].page_content
        if content not in unique_results:
            unique_results.add(content)
    
    print("number of unique results : {}".format(len(unique_results)))
    print("=======================")
    print()

    unique_results = list(unique_results)
    
    in_answer = "retrieve a passage that answers this question from some information"

    final_result = unique_results[0]
    
    for i in range(1, len(unique_results)):
        features = tokenizer(['{0} [SEP] {1}'.format(in_answer, user_query), '{0} [SEP] {1}'.format(in_answer, user_query)], 
                             [final_result, unique_results[i]], padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            scores = model(**features).logits
            normalized_scores = [float(score[1]) for score in F.softmax(scores, dim=1)]
        if np.argmax(normalized_scores) != 0:
            final_result = unique_results[i]

    result_dir = "results/0000/"
    if not os.path.isdir(result_dir):
        os.makedirs(result_dir)
    
    result_file = "0000_tart_stella1.5B_15Q_1st_.txt"
    
    with open(result_dir+result_file, "a") as output_file:
        output_file.write("Result {} :".format(query_no))
        output_file.write("\n")
        output_file.write(final_result)
        output_file.write("\n")
        output_file.write("\n")
        output_file.close()
    
    return final_result

# run this python file only when a new vector DB is going to be set up
if __name__ == "__main__":
    query_dir = "questions/"
    query_file = "questions_15.txt"

    with open(query_dir + query_file, 'r') as fr:
        user_queries = fr.read().split("\n")
        
    embedding_model = 'dunzhang/stella_en_1.5B_v5'
    
    chunk_size = 200
    # chunk_number = set_vector_db(chunk_size, embedding_model)
    
    num = 50
    
    # score = retrieve(user_query, num, embedding_model)
    
    # print()
    # print("Embedding Model = {} :".format(embedding_model))
    # print("average score = {}".format(score))
        
    retrieved_results = []

    model = EncT5ForSequenceClassification.from_pretrained("facebook/tart-full-flan-t5-xl")
    tokenizer =  EncT5Tokenizer.from_pretrained("facebook/tart-full-flan-t5-xl")

    model.eval()

    for i in range(len(user_queries)):
        query = user_queries[i]
        result = retrieve_with_re_ranker(query, num, embedding_model, model, tokenizer, i)
        retrieved_results.append(result)
        gc.collect()

    result_dir = "results/0000/"
    
    '''result_file = "0000_tart_stella1.5B_15Q_1st_.txt"
    
    with open(result_dir+result_file, "r") as retrieved_file:
        retrieved_list = retrieved_file.read().split("Result ")
        for retrieved_result in retrieved_list:
            if "\n" not in retrieved_result:
                continue
            retrieved_results.append(retrieved_result.split("\n")[1])'''
    
    result_file = "0000_tart_stella1.5B_15Q_1st_Ans.txt"
    
    with open(result_dir+result_file, "w") as output_file:
        for i in range(len(retrieved_results)):
            histories = ""

            retrieved_result = retrieved_results[i]

            generation_reranker = generate_with_loop("Here is a question : " + user_queries[i] + " And I give you a related document : " + retrieved_result + " Generate a answer for me.", histories)

            answer_reranker = ""

            for ans in generation_reranker:
                answer_reranker = ans
            
            output_file.write("Answer {} :".format(i))
            output_file.write("\n")
            output_file.write(answer_reranker)
            output_file.write("\n")
            output_file.write("\n")