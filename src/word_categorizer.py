import argparse
import os
import pickle

import numpy as np
from sklearn.cluster import KMeans, DBSCAN, OPTICS
from sklearn.preprocessing import normalize
from spherecluster import SphericalKMeans, VonMisesFisherMixture
from tqdm import tqdm


class WordCategorizer:
    def __init__(self):
        self.matrix = None  # Stores sent probability for each word-sentence pair (rows are words)
        self.wsd_matrix = None  # Stores sent probability for each word sense-sentence pair (rows are words)
        self.sentences = None  # List of corpus textual sentences
        self.vocab_map = None  # Dictionary with counts and coordinates of every occurrence of each word
        self.wsd_centroids = None  # Stores centroids for disambiguated senses
        self.estimator = None  # Clustering method
        self.disamb_vocab = []

    def load_centroids(self, pickle_senses):
        """
        Load ambiguous word senses, as stored by word_senser.py
        :param pickle_senses:
        :return:
        """
        try:
            with open(pickle_senses, 'rb') as fs:
                self.wsd_centroids= pickle.load(fs)
            print("WSD data successfully loaded!\n")
        except:
            print("ERROR: Loading WSD data failed!!\n")
            exit(1)

    def load_matrix(self, pickle_emb, verbose=False):
        """
        If pickle file is present, load data; else, calculate it.
        :param pickle_emb:          File to load embeddings
        :param verbose:
        :return:
        """
        try:
            with open(pickle_emb, 'rb') as h:
                _data = pickle.load(h)
                self.sentences = _data[0]
                self.vocab_map = _data[1]
                self.matrix = _data[2]

            print("MATRIX FOUND!")

        except:
            print("MATRIX File Not Found!! \n")
            exit(1)

    def restructure_matrix(self):
        """
        For each sentence, sentence probability scores are assigned to the correct word sense if word
        is ambiguous according to WSD data.
        Each instance only contributes to the embedding vector of the closest sense.
        """
        # Store nbr senses per word
        sense_counts = []
        for word, sense_centroids in self.wsd_centroids.items():
            sense_counts.append(len(sense_centroids))
            self.disamb_vocab.extend([word] * len(sense_centroids))
        # sense_counts = [len(sense_centroids) for sense_centroids in self.wsd_centroids.values()]
        total_senses = sum(sense_counts)
        total_instances = len(self.matrix)
        self.wsd_matrix = np.zeros([total_instances, total_senses])  # Init wsd matrix with zeros
        for row_id, embedding in enumerate(self.matrix):
            for column_id, centroids in enumerate(self.wsd_centroids.values()):
                if centroids == [0]:  # If word is not ambiguous
                    closest_sense = 0
                else:
                    # Estimate closest sense if word is ambiguous
                    closest_sense = np.argmax(np.dot(embedding, np.transpose(centroids)))
                wsd_column_id = sum(sense_counts[:column_id]) + closest_sense
                self.wsd_matrix[row_id, wsd_column_id] = self.matrix[row_id][column_id]  # Assign to closest sense

        self.wsd_matrix = normalize(self.wsd_matrix, axis=0)  # Normalize restructured word-sense embeddings
        print("Matrix restructured with WSD data!")

    def cluster_words(self, clust_method='SphericalKMeans', **kwargs):
        min_samples = int(kwargs.get('min_samples', 3))
        eps = kwargs.get('eps', 0.3)
        k = int(kwargs.get('k', 5))  # 5 is default value, if no kwargs were passed
        # Init clustering object
        if clust_method == 'OPTICS':
            self.estimator = OPTICS(min_samples=min_samples, metric='cosine', n_jobs=4)
        elif clust_method == 'DBSCAN':
            self.estimator = DBSCAN(min_samples=min_samples, metric='cosine', eps=eps, n_jobs=4)
        elif clust_method == 'KMeans':
            self.estimator = KMeans(init="k-means++", n_clusters=k, n_jobs=4)
        elif clust_method == 'SphericalKMeans':
            self.estimator = SphericalKMeans(n_clusters=k, n_jobs=4)
        elif clust_method == 'movMF-soft':
            self.estimator = VonMisesFisherMixture(n_clusters=k, posterior_type="soft")
        elif clust_method == 'movMF-hard':
            self.estimator = VonMisesFisherMixture(n_clusters=k, posterior_type="hard")
        else:
            print("Clustering methods implemented are: OPTICS, DBSCAN, KMeans, SphericalKMeans, movMF-soft, movMF-hard")
            exit(1)

        self.estimator.fit(np.transpose(self.wsd_matrix))  # Cluster word-senses into categories

    def write_clusters(self, method, save_to, clust_param):
        """
        Write clustering results to file
        :param save_to:        Directory to save disambiguated senses
        :param method:         Clustering method used
        """
        num_clusters = max(self.estimator.labels_) + 1
        print(f"Writing {num_clusters} clusters to file")

        # Write word categories to file
        append = "/" + method + "_" + str(clust_param)
        with open(save_to + append + '.wordcat', "w") as fo:
            for i in range(-1, num_clusters):  # Also write unclustered words
                cluster_members = [self.disamb_vocab[j] for j, k in enumerate(self.estimator.labels_) if k == i]
                fo.write(f"Cluster #{i}")
                if len(cluster_members) > 0:  # Handle empty clusters
                    fo.write(": \n[")
                    np.savetxt(fo, cluster_members, fmt="%s", newline=", ")
                    fo.write(']\n')
                else:
                    fo.write(" is empty\n\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Word categorization using BERT')
    parser.add_argument('--clusterer', type=str, default='KMeans', help='Clustering method to use')
    parser.add_argument('--start_k', type=float, default=10, help='Initial value of clustering param')
    parser.add_argument('--end_k', type=float, default=10, help='Final value of clustering param')
    parser.add_argument('--steps_k', type=int, default=1, help='Step for clustering param exploration')
    parser.add_argument('--save_to', type=str, default='test', help='Directory to save word categories')
    parser.add_argument('--verbose', action='store_true', help='Print processing details')
    parser.add_argument('--pickle_WSD', type=str, required=False, help='Pickle file WSD info')
    parser.add_argument('--pickle_emb', type=str, default='test.pickle', help='Pickle file with embeddings matrix')
    args = parser.parse_args()

    wc = WordCategorizer()

    # Load probability matrix for sentence-word pairs
    wc.load_matrix(args.pickle_emb, verbose=args.verbose)

    # Load WSD data
    if args.pickle_WSD:
        print("Word senses file found")
        wc.load_centroids(args.pickle_WSD)
        # Restructure matrix with WSD info
        wc.restructure_matrix()
    else:
        wc.wsd_matrix = wc.matrix  # point to same matrix if no WSD data

    print("Start clustering...")
    if not os.path.exists(args.save_to):
        os.makedirs(args.save_to)
    with open(args.save_to + '/results.log', 'w') as fl:
        for curr_k in tqdm(np.linspace(args.start_k, args.end_k, args.steps_k)):
            print(f"Clustering with k={curr_k}")
            wc.cluster_words(clust_method=args.clusterer, k=curr_k)
            wc.write_clusters(args.clusterer, args.save_to, curr_k)
