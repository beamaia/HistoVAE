import tensorflow as tf
from keras.layers import (
    Input, Dense, Conv2D, MaxPooling2D,
    UpSampling2D, Flatten, Reshape, Dropout
)
from keras.preprocessing.image import ImageDataGenerator
from keras.models import Model
from keras.callbacks import (
    Callback, TensorBoard, ModelCheckpoint
)
from keras.layers import LeakyReLU, Lambda, Layer
from keras.optimizers import Adam, RMSprop
from keras import metrics
from keras import backend as K
import numpy as np
import logging
from itertools import cycle
from tqdm import tqdm
logger = logging.getLogger(__name__)
from .callbacks import TensorBoardImage


class ConvolutionalAutoencoder():
    def __init__(self, inner_dim, dropout_rate=0):
        self.inner_dim = inner_dim
        self.dropout_rate = dropout_rate

    def encode(self, input_img):
        x = Conv2D(
            16, (3, 3),
            padding='same'
        )(input_img)
        x = LeakyReLU()(x)
        x = MaxPooling2D((2, 2), padding='same')(x)
        x = Conv2D(
            32, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = MaxPooling2D((2, 2), padding='same')(x)
        x = Conv2D(
            64, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = MaxPooling2D((2, 2), padding='same')(x)
        x = Conv2D(
            128, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = MaxPooling2D((2, 2), padding='same')(x)
        self.middle_tensor_shape = x.shape.as_list()[1:]
        self.middle_dim = np.prod(
            self.middle_tensor_shape
        )
        x = Flatten()(x)
        if self.dropout_rate > 0:
            x = Dropout(self.dropout_rate)(x)

        encoded = Dense(
            self.inner_dim,
            activity_regularizer='l2'
        )(x)
        return encoded

    def decode(self, input):
        x = input
        if self.dropout_rate > 0:
            x = Dropout(self.dropout_rate)(x)
        x = Dense(self.middle_dim)(x)
        x = Reshape(self.middle_tensor_shape)(x)
        x = Conv2D(
            128, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = UpSampling2D((2, 2))(x)
        x = Conv2D(
            64, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = UpSampling2D((2, 2))(x)
        x = Conv2D(
            32, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = UpSampling2D((2, 2))(x)
        x = Conv2D(
            16, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = UpSampling2D((2, 2))(x)
        decoded = Conv2D(
            3, (3, 3), activation='sigmoid',
            padding='same'
        )(x)
        return decoded

    def build(self, patches_data, params):
        N = patches_data.shape[0]
        self.params = params
        self.params['N'] = N

        self.name = (
            f"CA_ps{self.params['patch_size']}_"
            f"n{self.params['N']}_e{self.params['epochs']}_"
            f"lr{self.params['lr']}_bs{self.params['batch_size']}_"
            f"dim{self.params['inner_dim']}_do{self.params['dropout_rate']}"
        )
        input_img = Input(
            shape=(
                self.params['patch_size'],
                self.params['patch_size'],
                3
            )
        )
        model = Model(
            input_img,
            self.decode(self.encode(input_img))
        )
        self.model = model
        return model

    def train_on_data(self, patches_data, params):

        adam = Adam(
            lr=params['lr'], beta_1=params['beta_1']
        )

        model = self.build(patches_data, params)

        model.compile(
            optimizer=adam,
            loss='mean_squared_error',
        )

        datagen = ImageDataGenerator(
            horizontal_flip=True,
            vertical_flip=True
        )

        logger.debug('Fitting model')
        model.fit_generator(
            datagen.flow(
                patches_data, patches_data, batch_size=params['batch_size']
            ),
            steps_per_epoch=self.params['N'] / params['batch_size'],
            epochs=params['epochs'],
            callbacks=[
                TensorBoard(
                    log_dir=(
                        f'./tensorboardlogs/{self.name}'
                    )
                ),
                TensorBoardImage(patches_data, self.name)
            ],
        )
        self.model = model

    def save(self):
        assert self.model, "Model must be trained first"
        self.model.save("models/" + self.name + ".pkl")


class VariationalConvolutionalAutoencoder(object):
    def __init__(self, inner_dim, dropout_rate=0):
        self.inner_dim = inner_dim
        self.dropout_rate = dropout_rate
        self.epsilon_std = 1.0

    def encode(self, input_img):
        x = Conv2D(
            16, (3, 3),
            padding='same'
        )(input_img)
        x = LeakyReLU()(x)
        x = MaxPooling2D((2, 2), padding='same')(x)
        x = Conv2D(
            32, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = MaxPooling2D((2, 2), padding='same')(x)
        x = Conv2D(
            64, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = MaxPooling2D((2, 2), padding='same')(x)
        x = Conv2D(
            128, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = MaxPooling2D((2, 2), padding='same')(x)
        self.middle_tensor_shape = x.shape.as_list()[1:]
        self.middle_dim = np.prod(
            self.middle_tensor_shape
        )
        x = Flatten()(x)
        if self.dropout_rate > 0:
            x = Dropout(self.dropout_rate)(x)

        z_mean = Dense(self.inner_dim)(x)
        z_log_var = Dense(self.inner_dim)(x)

        inner_dim = self.inner_dim
        epsilon_std = self.epsilon_std

        def sampling(args):
            z_mean, z_log_var = args
            epsilon = K.random_normal(
                shape=(K.shape(z_mean)[0], inner_dim),
                mean=0., stddev=epsilon_std
            )
            return z_mean + K.exp(z_log_var) * epsilon

        z = Lambda(
            sampling, output_shape=(self.inner_dim,)
        )([z_mean, z_log_var])

        self.z_mean = z_mean
        self.z_log_var = z_log_var

        return z

    def decode(self, input):
        x = input
        if self.dropout_rate > 0:
            x = Dropout(self.dropout_rate)(x)
        x = Dense(self.middle_dim)(x)
        x = Reshape(self.middle_tensor_shape)(x)
        x = Conv2D(
            128, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = UpSampling2D((2, 2))(x)
        x = Conv2D(
            64, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = UpSampling2D((2, 2))(x)
        x = Conv2D(
            32, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = UpSampling2D((2, 2))(x)
        x = Conv2D(
            16, (3, 3), padding='same'
        )(x)
        x = LeakyReLU()(x)
        x = UpSampling2D((2, 2))(x)
        decoded = Conv2D(
            3, (3, 3), activation='sigmoid',
            padding='same'
        )(x)
        return decoded

    def build(self, patches_data, params):

        N = patches_data.shape[0]
        self.params = params
        self.params['N'] = N

        self.name = (
            f"VCA_ps{self.params['patch_size']}_"
            f"n{self.params['N']}_e{self.params['epochs']}_"
            f"lr{self.params['lr']}_bs{self.params['batch_size']}_"
            f"dim{self.params['inner_dim']}_do{self.params['dropout_rate']}"
            "ps*mse"
        )
        input_img = Input(
            shape=(
                self.params['patch_size'],
                self.params['patch_size'],
                3
            )
        )

        input_img_decoded = self.decode(self.encode(input_img))

        model = Model(input_img, input_img_decoded)
        self.model = model
        return model

    def train_on_data(self, patches_data, params):

        # rmsprop = RMSprop(
        #     0.001, epsilon=1.0
        # )

        adam = Adam(
            lr=params['lr'], beta_1=params['beta_1']
        )

        self.model = self.build(patches_data, params)

        def vae_loss(x, x_decoded_mean_squash):
            x = K.flatten(x)
            x_decoded_mean_squash = K.flatten(x_decoded_mean_squash)
            xent_loss = patches_data.shape[1] * metrics.mean_squared_error(
                x, x_decoded_mean_squash
            )
            kl_loss = - 0.5 * K.mean(1 + self.z_log_var
                                     - K.square(self.z_mean)
                                     - K.exp(self.z_log_var), axis=-1)
            return K.mean(xent_loss + kl_loss)

        self.model.compile(
            optimizer=adam, loss=vae_loss
        )

        datagen = ImageDataGenerator(
            horizontal_flip=True,
            vertical_flip=True
        )

        logger.debug('Fitting model')





        self.model.fit_generator(
            datagen.flow(
                patches_data, patches_data, batch_size=params['batch_size']
            ),
            steps_per_epoch=self.params['N'] / params['batch_size'],
            epochs=params['epochs'],
            callbacks=[
                TensorBoard(
                    log_dir=(
                        f'./tensorboardlogs/{self.name}'
                    )
                ),
                TensorBoardImage(patches_data, self.name)
            ],
        )

    def save(self):
        assert self.model, "Model must be trained first"
        self.model.save("models/" + self.name + ".pkl")
