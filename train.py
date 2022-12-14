from argparse import ArgumentParser
from multiprocessing import Pool
import os
import sys

import pytorch_lightning as pl
from pytorch_lightning.callbacks import ModelCheckpoint
from pytorch_lightning.callbacks.early_stopping import EarlyStopping
from pytorch_lightning.loggers import TensorBoardLogger, WandbLogger
from pytorch_lightning import Trainer

import torch
import torch.utils.data as data
import random
from numpy.random import RandomState
import numpy as np

from Model.lightning_model import LightningModelPairNet, LightningModelTripleNet, ModelNames

from Dataset.dataset import VOC, VOCDataset

from utils.multibox import MultiBox
from utils.transform import *

# SEED
def seed_torch(seed=100):
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed) # if you are using multi-GPU.
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    pl.utilities.seed.seed_everything(seed)

seed_torch()


if __name__ == "__main__":

    parser = ArgumentParser(add_help=True)
    parser.add_argument('--voc_root', type=str, default='VOCdevkit')
    parser.add_argument('--batch_size', type=int, default=4)
    parser.add_argument('--epochs', type=int, default=480)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--gpu', type=int, default=-1)
    parser.add_argument('--dev', type=str, default=False)
    parser.add_argument('--n_workers', type=int, default=4)
    parser.add_argument('--n_classes', type=int, default=20)
    parser.add_argument('--model', type=str, default=ModelNames.PairNet.value)
    parser.add_argument('--voc_year', type=str, default='2007')
    parser.add_argument('--model_checkpoint', type=str, default=None)
    parser.add_argument('--upstream_model', type=str, default=None)
    parser.add_argument('--sizes', type=list, default=[s / 300. for s in [30, 60, 111, 162, 213, 264, 315]])
    parser.add_argument('--aspect_ratios', type=list, default=(1/4., 1/3.,  1/2.,  1,  2,  3))
    parser.add_argument('--grids', type=list, default=[38, 19, 10, 5, 3, 2])
    parser.add_argument('--run_name', type=str, default='pairnet')

    parser = pl.Trainer.add_argparse_args(parser)
    cfg = parser.parse_args()
    cfg = vars(cfg)

    print('Training Model on TIMIT Dataset\n#Cores = {}\t#GPU = {}'.format(cfg['n_workers'], cfg['gpu']))

    encoder = MultiBox(cfg)

    transform = Compose([
            [ColorJitter(prob=0.5)],
            BoxesToCoords(),
            HorizontalFlip(),
            Resize(300),
            CoordsToBoxes(),
            [SubtractMean(mean=VOC.MEAN)],
            [RGB2BGR()],
            [ToTensor()],
            ], RandomState(233), mode=None, fillval=VOC.MEAN)
    target_transform = encoder.encode


    # Training, Validation and Testing Dataset
    ## Training Dataset
    train_set = VOCDataset(
        root=cfg['voc_root'], 
        image_set=[(cfg['voc_year'], 'train')],
        keep_difficult=True,
        transform=transform,
        target_transform=target_transform
    )
    ## Training DataLoader
    trainloader = data.DataLoader(
        train_set, 
        batch_size=cfg['batch_size'], 
        shuffle=True, 
        num_workers=cfg['n_workers']
    )
    ## Validation Dataset
    valid_set = VOCDataset(
        root=cfg['voc_root'], 
        image_set=[(cfg['voc_year'], 'val')],
        keep_difficult=True,
        transform=transform,
        target_transform=target_transform
    )

    ## Validation Dataloader
    valloader = data.DataLoader(
        valid_set, 
        batch_size=cfg['batch_size'],
        shuffle=False, 
        num_workers=cfg['n_workers']
    )

    print('Dataset Split (Train, Validation, Test)=', len(train_set), len(valid_set))


    logger = WandbLogger(
        name=cfg['run_name'],
        project='DL',
        offline=True
    )

    if cfg['model'] == ModelNames.PairNet.value:
        model = LightningModelPairNet(cfg)
        print("Model: PairNet")
    elif cfg['model'] == ModelNames.TripleNet.value:
        model = LightningModelTripleNet(cfg)
        print("Model: TripleNet")
    else:
        print("ERROR: Invalid model in parameters.")
        sys.exit()
        


    model_checkpoint_callback = ModelCheckpoint(
        dirpath='checkpoints/{}'.format(cfg['run_name'] + cfg['voc_year']),
        monitor='val/loss', 
        mode='min',
        verbose=1)

    trainer = Trainer(
        fast_dev_run=cfg['dev'], 
        gpus=cfg['gpu'], 
        max_epochs=cfg['epochs'], 
        callbacks=[
            EarlyStopping(
                monitor='val/loss',
                min_delta=0.00,
                patience=15,
                verbose=True,
                mode='min'
                ),
            model_checkpoint_callback
        ],
        logger=logger,
        resume_from_checkpoint=cfg['model_checkpoint'],
        distributed_backend='ddp',
        auto_lr_find=True
    )
    
    trainer.fit(model, train_dataloaders=trainloader, val_dataloaders=valloader)

    print('\n\nCompleted Training...\nTesting the model with checkpoint -', model_checkpoint_callback.best_model_path)
