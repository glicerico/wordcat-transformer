import pickle
import xml.etree.ElementTree as ET
import torch
import argparse
import numpy as np

from transformers import BertTokenizer, BertModel
from sklearn.cluster import KMeans
from sklearn.cluster import OPTICS, DBSCAN

from tqdm import tqdm, trange
import warnings

warnings.filterwarnings('ignore')


class BERT:

    def __init__(self, pretrained_model, device_number='cuda:2', use_cuda=True):
        self.device_number = device_number
        self.use_cuda = use_cuda

        self.tokenizer = BertTokenizer.from_pretrained(pretrained_model)

        self.model = BertModel.from_pretrained(pretrained_model, output_hidden_states=True)
        self.model.eval()

        if use_cuda:
            self.model.to(device_number)


class WordSenseModel:

    def __init__(self, pretrained_model, device_number='cuda:2', use_cuda=True):

        self.device_number = device_number
        self.use_cuda = use_cuda

        self.Bert_Model = BERT(pretrained_model, device_number, use_cuda)

    def open_xml_file(self, file_name):

        tree = ET.parse(file_name)
        root = tree.getroot()

        return root, tree

    def semeval_sent_sense_collect(self, xml_struct):

        _sent = []
        _sent1 = ""
        _senses = []

        for idx, j in enumerate(xml_struct.iter('word')):

            _temp_dict = j.attrib

            words = _temp_dict['surface_form'].lower()

            if '*' not in words:

                _sent1 += words + " "

                _sent.extend([words])

                if 'wn30_key' in _temp_dict:

                    _senses.extend([_temp_dict['wn30_key']] * len([words]))

                else:
                    _senses.extend([0] * len([words]))

        return _sent, _sent1, _senses

    def apply_bert_tokenizer(self, word):

        return self.Bert_Model.tokenizer.tokenize(word)

    def collect_bert_tokens(self, _sent):

        _bert_tokens = ['[CLS]', ]

        for idx, j in enumerate(_sent):
            _tokens = self.apply_bert_tokenizer(_sent[idx])

            _bert_tokens.extend(_tokens)

        _bert_tokens.append('[SEP]')

        return _bert_tokens

    def get_bert_embeddings(self, tokens):

        _ib = self.Bert_Model.tokenizer.convert_tokens_to_ids(tokens)
        _st = [0] * len(_ib)

        if self.use_cuda:

            _t1, _t2 = torch.tensor([_ib]).to(self.device_number), torch.tensor([_st]).to(self.device_number)

        else:
            _t1, _t2 = torch.tensor([_ib]), torch.tensor([_st])

        with torch.no_grad():

            _, _, _encoded_layers = self.Bert_Model.model(_t1, token_type_ids=_t2)

            _e1 = _encoded_layers[-4:]

            _e2 = torch.cat((_e1[0], _e1[1], _e1[2], _e1[3]), 2)

            if self.use_cuda:
                _final_layer = _e2[0].cpu().numpy()

            else:
                _final_layer = _e2[0].numpy()
                _final_layer = np.around(_final_layer, decimals=5)  # LOWER PRECISION, process faster. CHECK if good!!

        return _final_layer

    def load_embeddings(self, pickle_file_name, corpus_file):
        """
        First pass on the corpus sentences. If pickle file is present, load data; else, calculate it.
        This method:
          a) Stores sentences as an array.
          b) Creates dictionary where each vocabulary word is mapped to its occurrences in corpus.
          c) Calculates embeddings for each vocabulary word.
        :param pickle_file_name:
        :param corpus_file:
        :return: sentences, vocab_map, embeddings
        """
        try:

            with open(pickle_file_name, 'rb') as h:
                _x, _y, _z = pickle.load(h)

                print("EMBEDDINGS FOUND!")
                return _x, _y, _z

        except:

            print("Embedding File Not Found!! \n")
            print("Performing first pass...")

            _x, _y, _z = self.calculate_embeddings(corpus_file=corpus_file)

            with open(pickle_file_name, 'wb') as h:
                pickle.dump((_x, _y, _z), h)

            print("Data stored in " + pickle_file_name)

            return _x, _y, _z

    def calculate_embeddings(self, corpus_file):
        """
        Finds BERT data for all words in corpus_file, and writes them to file
        :param corpus_file:     file to obtain vocabulary from
        :return: data:    data for the words in corpus_file
        """

        _test_root, _test_tree = self.open_xml_file(corpus_file)

        embeddings_count = 0
        all_embeddings = []
        words = []

        for i in tqdm(_test_root.iter('sentence')):

            sent, sent1, senses = self.semeval_sent_sense_collect(i)

            bert_tokens = self.collect_bert_tokens(sent)

            final_layer = self.get_bert_embeddings(bert_tokens)

            token_count = 1

            for idx, j in enumerate(zip(senses, sent)):
                word = j[1]
                embedding = np.mean(final_layer[token_count:token_count + len(self.apply_bert_tokenizer(word))], 0)
                all_embeddings.append(embedding)
                token_count += len(self.apply_bert_tokenizer(word))

                words.append(word)
                embeddings_count += 1

        print(f"{embeddings_count} EMBEDDINGS GENERATED")

        return all_embeddings, words

    def cluster_embeddings(self, data, words, cluster_file, k):
        """
        Cluster the data vectors using an sklearn algorithm, and write clusters to file

        :param data:            Embeddings to cluster
        :param words:           Words corresponding to each data vector
        :param cluster_file:    File to write the clusters
        :param kwargs:
        """
        estimator = KMeans(init="k-means++", n_clusters=k, n_jobs=4)
        # estimator = OPTICS(min_samples=3, cluster_method='dbscan', metric='cosine', max_eps=0.1, eps=0.1)
        # estimator = DBSCAN(metric='cosine', n_jobs=4, min_samples=4, eps=0.3)
        data = np.float32(data)
        estimator.fit(data)
        print(estimator.labels_)
        num_clusters = max(estimator.labels_) + 1

        with open(cluster_file, "w") as fo:
            words = np.array(words)
            for i in range(num_clusters):
                print(f"Cluster #{i}:")
                fo.write(f"Cluster #{i}:\n[")
                # print(estimator.labels_==i)
                category = words[estimator.labels_ == i]
                print(category)
                # category.tofile(fo, sep=", ")
                np.savetxt(fo, category, fmt="%s", newline=", ")
                fo.write(']\n')
            print("Finished clustering")

        print(f"Num clusters: {num_clusters}")


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='WSD using BERT')

    parser.add_argument('--no_cuda', action='store_false', help='Use GPU?')
    parser.add_argument('--device', type=str, default='cuda:2', help='GPU Device to Use?')
    parser.add_argument('--corpus', type=str, required=True, help='Training Corpus')
    parser.add_argument('--start_k', type=int, default=1, help='First number of clusters to use')
    parser.add_argument('--end_k', type=int, default=1, help='Final number of clusters to use')
    parser.add_argument('--step_k', type=int, default=5, help='Increase in number of clusters to use')
    parser.add_argument('--embeddings_file', type=str, help='Where to save the data')
    parser.add_argument('--pickle_file', type=str, help='Pickle file of Bert Embeddings/Save Embeddings to file')
    parser.add_argument('--pretrained', type=str, default='bert-large-uncased', help='Pretrained model to use')
    parser.add_argument('--use_euclidean', type=int, default=0, help='Use Euclidean Distance to Find NNs?')

    args = parser.parse_args()

    print("Corpus is: " + args.corpus)
    # print("Number of clusters: " + str(args.end_k))

    if args.no_cuda:
        print("Processing with CUDA!")

    else:
        print("Processing without CUDA!")

    if args.use_euclidean:
        print("Using Euclidean Distance!")

    else:
        print("Using Cosine Similarity!")

    print("Loading WSD Model!")

    WSD = WordSenseModel(args.pretrained, device_number=args.device, use_cuda=args.no_cuda)

    print("Loaded WSD Model!")

    embeddings, labels = WSD.first_pass(args.pickle_file, args.corpus)

    for nn in range(args.start_k, args.end_k + 1, args.step_k):
        save_to = args.embeddings_file[:-4] + "_" + str(nn) + args.embeddings_file[-4:]
        WSD.cluster_embeddings(embeddings, labels, save_to, nn)
