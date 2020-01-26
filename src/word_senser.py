import os
import pickle
import xml.etree.ElementTree as ET
import torch
import argparse
import numpy as np
import random as rand

from transformers import BertTokenizer, BertModel
from sklearn.cluster import KMeans, OPTICS, DBSCAN, cluster_optics_dbscan

from tqdm import tqdm
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

        self.sentences = []  # List of corpus textual sentences
        self.vocab_map = {}  # Dictionary that stores coordinates of every occurrence of each word
        self.embeddings = []  # Embeddings for all words in corpus

        self.device_number = device_number
        self.use_cuda = use_cuda

        self.Bert_Model = BERT(pretrained_model, device_number, use_cuda)

    @staticmethod
    def open_xml_file(file_name):

        tree = ET.parse(file_name)
        root = tree.getroot()

        return root, tree

    @staticmethod
    def semeval_sent_sense_collect(xml_struct):

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

            # Average last 4 hidden layers (second best result from Devlin et al. 2019)
            _e1 = _encoded_layers[-4:]
            _e2 = torch.cat((_e1[0], _e1[1], _e1[2], _e1[3]), 0)
            _e3 = torch.mean(_e2, dim=0)

            if self.use_cuda:
                _final_layer = _e3.cpu().numpy()

            else:
                _final_layer = _e3.numpy()
                _final_layer = np.around(_final_layer, decimals=5)  # LOWER PRECISION, process faster. CHECK if good!!

        return _final_layer

    def load_embeddings(self, pickle_file_name, corpus_file):
        """
        First pass on the corpus sentences. If pickle file is present, load data; else, calculate it.
        This method:
          a) Stores sentences as an array.
          b) Creates dictionary where each vocabulary word is mapped to its occurrences in corpus.
          c) Calculates embeddings for each vocabulary word.
        :param pickle_file_name
        :param corpus_file
        """
        try:

            with open(pickle_file_name, 'rb') as h:
                _data = pickle.load(h)
                self.sentences = _data[0]
                self.vocab_map = _data[1]
                self.embeddings = _data[2]

                print("EMBEDDINGS FOUND!")

        except:

            print("Embedding File Not Found!! \n")
            print("Performing first pass...")

            self.calculate_embeddings(corpus_file=corpus_file)

            with open(pickle_file_name, 'wb') as h:
                _data = (self.sentences, self.vocab_map, self.embeddings)
                pickle.dump(_data, h)

            print("Data stored in " + pickle_file_name)

    def calculate_embeddings(self, corpus_file):
        """
        Calculates embeddings for all words in corpus_file, creates vocabulary dictionary
        :param corpus_file:     file to obtain vocabulary from
        """

        _test_root, _test_tree = self.open_xml_file(corpus_file)

        embeddings_count = 0

        # Process each sentence in corpus
        for sent_nbr, i in tqdm(enumerate(_test_root.iter('sentence'))):
            sent_embeddings = []  # Store one sentence's word embeddings as elements

            sent, sent1, senses = self.semeval_sent_sense_collect(i)
            self.sentences.append(sent1)

            bert_tokens = self.collect_bert_tokens(sent)

            final_layer = self.get_bert_embeddings(bert_tokens)

            token_count = 1

            # Process all words in sentence
            for word_pos, j in enumerate(sent):
                word = j
                # Register word location in vocabulary dictionary
                if word not in self.vocab_map.keys():
                    self.vocab_map[word] = []
                self.vocab_map[word].append((sent_nbr, word_pos))

                embedding = np.mean(final_layer[token_count:token_count + len(self.apply_bert_tokenizer(word))], 0)
                sent_embeddings.append(np.float32(embedding))  # Lower precision for speed
                token_count += len(self.apply_bert_tokenizer(word))

                embeddings_count += 1

            # Store this sentence embeddings in the general list
            self.embeddings.append(sent_embeddings)

        print(f"{embeddings_count} EMBEDDINGS GENERATED")

    def disambiguate(self, save_dir, clust_method='OPTICS', freq_threshold=5, **kwargs):
        """
        Disambiguate word senses through clustering their transformer embeddings
        Clustering is done using the selected sklearn algorithm.
        If OPTICS method is used, then DBSCAN clusters are also obtained

        :param save_dir:        Directory to save disambiguated senses
        :param clust_method:    Clustering method used
        :param freq_threshold:  Frequency threshold for a word to be disambiguated
        :param kwargs:          Clustering parameters
        """

        # k = kwargs.get('k', 10)  # 10 is default value, if no kwargs were passed
        # freq_threshold = max(freq_threshold, k)
        # estimator = KMeans(init="k-means++", n_clusters=k, n_jobs=4)
        # estimator = DBSCAN(metric='cosine', n_jobs=4, min_samples=5, eps=0.3)

        # Use OPTICS estimator also to get DBSCAN clusters
        if clust_method == 'OPTICS':
            min_samples = kwargs.get('min_samples', 0.2)  # at least 20% of instances in a sense
            max_eps = kwargs.get('max_eps', 0.5)  # max distance to be neighbors

            # Init clustering object
            estimator = OPTICS(min_samples=min_samples, metric='cosine', n_jobs=4, max_eps=max_eps)
            save_to = save_dir + "_OPTICS_minsamp" + str(min_samples) + "_maxeps" + str(max_eps)
            if not os.path.exists(save_to):
                os.makedirs(save_to)
            fl = open(save_to + "/clustering.log", 'w')  # Logging file
            fl.write(f"# WORD\t\tCLUSTERS\n")

            # directory and files setup for dbscan clustering
            eps_dbscan = np.linspace(0.1, max_eps, round(max_eps / 0.1))  # eps intervals to use in dbscan
            fl_dbscan = []
            save_dbscan = []
            for eps_val in eps_dbscan:
                this_save = save_to + f"/DBSCAN_eps{eps_val:02}"  # FIX: Format doesn't work
                if not os.path.exists(this_save):
                    os.makedirs(this_save)
                save_dbscan.append(this_save)
                fl_dbscan.append(open(this_save + "/clustering.log", 'w'))

            # Loop for each word in vocabulary
            for word, instances in self.vocab_map.items():
                if len(instances) < freq_threshold:  # Don't disambiguate if word is uncommon
                    print(f"Word \"{word}\" frequency out of threshold")
                    continue
                else:
                    print(f'Disambiguating word \"{word}\"...')

                # Build embeddings list for this word
                curr_embeddings = []
                for instance in instances:
                    x, y = instance  # Get current word instance coordinates
                    curr_embeddings.append(self.embeddings[x][y])

                estimator.fit(curr_embeddings)  # Disambiguate
                self.write_clusters(fl, save_to, word, estimator.labels_)

                # Use OPTICS estimator to do DBSCAN in range of eps values
                for eps_val, this_fl, this_save in zip(eps_dbscan, fl_dbscan, save_dbscan):
                    this_labels = cluster_optics_dbscan(reachability=estimator.reachability_,
                                                        core_distances=estimator.core_distances_,
                                                        ordering=estimator.ordering_, eps=eps_val)
                    self.write_clusters(this_fl, this_save, word, this_labels)

            for this_fl in fl_dbscan:
                this_fl.write("\n")
                this_fl.close()

            fl.write("\n")
            fl.close()

    def write_clusters(self, fl, save_dir, word, labels):
        """
        Perform the clustering and writing results to file
        :param fl:              handle for logging file
        :param save_dir:        Directory to save disambiguated senses
        :param word:            Current word to disambiguate
        :param labels:          Cluster labels for each word instance
        """

        num_clusters = max(labels) + 1
        print(f"Num clusters: {num_clusters}")
        fl.write(f"{word}\t\t{num_clusters}\n")

        # If disambiguated, write senses to file, with some sentence examples
        if num_clusters > 1:
            with open(save_dir + '/' + word + ".disamb", "w") as fo:
                for i in range(num_clusters):
                    fo.write(f"Cluster #{i}:\n[")
                    sense_members = [self.vocab_map[word][j] for j, k in enumerate(labels) if k == i]
                    np.savetxt(fo, sense_members, fmt="(%s, %s)", newline=", ")
                    fo.write(']\n')
                    # Write at most 3 sentence examples for the word sense
                    sent_samples = rand.sample(sense_members, min(len(sense_members), 3))
                    fo.write('Samples:\n')
                    # Write sample sentences to file, with focus word in CAPS for easier reading
                    for sample, focus_word in sent_samples:
                        bold_sent = self.sentences[sample].split()
                        bold_sent[focus_word] = bold_sent[focus_word].upper()
                        fo.write(" ".join(bold_sent) + '\n')


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='WSD using BERT')

    parser.add_argument('--no_cuda', action='store_false', help='Use GPU?')
    parser.add_argument('--device', type=str, default='cuda:2', help='GPU Device to Use?')
    parser.add_argument('--corpus', type=str, required=True, help='Training Corpus')
    parser.add_argument('--start_k', type=int, default=10, help='First number of clusters to use')
    parser.add_argument('--end_k', type=int, default=10, help='Final number of clusters to use')
    parser.add_argument('--step_k', type=int, default=5, help='Increase in number of clusters to use')
    parser.add_argument('--save_to', type=str, default='test', help='Directory to save disambiguated words')
    parser.add_argument('--pretrained', type=str, default='bert-large-uncased', help='Pretrained model to use')
    parser.add_argument('--use_euclidean', type=int, default=0, help='Use Euclidean Distance to Find NNs?')
    parser.add_argument('--pickle_file', type=str, default='test.pickle', help='Pickle file of Bert Embeddings/Save '
                                                                               'Embeddings to file')

    args = parser.parse_args()

    print("Corpus is: " + args.corpus)

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

    WSD.load_embeddings(args.pickle_file, args.corpus)

    print("Start disambiguation...")
    for nn in range(args.start_k, args.end_k + 1, args.step_k):
        WSD.disambiguate(args.save_to, freq_threshold=5)
