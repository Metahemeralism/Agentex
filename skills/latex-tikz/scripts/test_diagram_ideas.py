"""Run: python3 -m unittest discover skills/latex-tikz/scripts"""
import json
import tempfile
import unittest
from pathlib import Path

from diagram_ideas import suggest

FILES = {
    'models.py': '''
import torch.nn as nn
import torch.nn.functional as F

class BasicBlock(nn.Module):
    def __init__(self, c):
        super().__init__()
        self.conv1 = nn.Conv2d(c, c, 3)
        self.bn1 = nn.BatchNorm2d(c)
        self.conv2 = nn.Conv2d(c, c, 3)
    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.conv2(out)
        return out + x

class ResNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.stem = nn.Conv2d(3, 64, 7)
        self.blocks = nn.Sequential(BasicBlock(64), BasicBlock(64))
        self.head = nn.Linear(64, 10)
    def forward(self, x):
        return self.head(self.blocks(self.stem(x)))

class Encoder(nn.Module):
    def __init__(self, d):
        super().__init__()
        self.attn = nn.MultiheadAttention(d, 8)
        self.norm = nn.LayerNorm(d)
    def forward(self, x):
        return self.norm(x + self.attn(x, x, x)[0])
''',
    'train.py': '''
import json, torch
import pandas as pd
from models import ResNet

def load_data(): ...
def evaluate(model): ...

def train(model, loader, opt, epochs):
    for epoch in range(epochs):
        for xb, yb in loader:
            opt.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            opt.step()
        if evaluate(model) > 0.99:
            break
    torch.save(model.state_dict(), "checkpoints/best.pt")

def main():
    data = load_data()
    model = ResNet()
    train(model, data, None, 10)
    evaluate(model)
    pd.DataFrame().to_csv("results/metrics.csv")

if __name__ == "__main__":
    main()
''',
    'plots.py': '''
import pandas as pd
import matplotlib.pyplot as plt
df = pd.read_csv("results/metrics.csv")
plt.savefig("figures/loss.pdf")
''',
    'bayes.py': '''
import numpyro, numpyro.distributions as dist
def model(x, y=None):
    mu = numpyro.sample("mu", dist.Normal(0, 1))
    sigma = numpyro.sample("sigma", dist.HalfNormal(1))
    with numpyro.plate("N", len(x)):
        numpyro.sample("y", dist.Normal(mu, sigma), obs=y)
''',
    'sim.py': '''
from enum import Enum
import numpy as np
class Phase(Enum):
    WARMUP = 1
    RUN = 2
    COOLDOWN = 3
def attention(q, k):
    return np.einsum("bhqd,bhkd->bhqk", q, k)
def solve(A, b, tol=1e-6):
    x, residual = b, 1.0
    while residual > tol:
        residual = residual / 2
    return x
''',
    'results/metrics.csv': 'epoch,train_loss,val_loss\n1,0.9,1.0\n',
}

NOTEBOOK = {'cells': [{'cell_type': 'code', 'source': ['%matplotlib inline\n', 'import numpy as np\n']},
                      {'cell_type': 'markdown', 'source': ['# notes']},
                      {'cell_type': 'code', 'source': ['def step(X):\n', '    for t in range(9):\n', '        X[t + 1] = X[t] * 2\n']}]}


class DiagramIdeasTest(unittest.TestCase):
    def test_detectors(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, text in FILES.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
            (root / 'explore.ipynb').write_text(json.dumps(NOTEBOOK))
            high, comp, n, skipped, _ = suggest(root, max_ideas=20)
        titles = {i['title']: i for i in high + comp}
        self.assertEqual((n, skipped), (6, 0))
        self.assertIn('End-to-end pipeline (train.py)', titles)
        self.assertIn('load_data -> ResNet -> train -> evaluate', titles['End-to-end pipeline (train.py)']['detail'])
        self.assertIn('Artefact flow between scripts', titles)
        self.assertIn('results/metrics.csv => plots.py', titles['Artefact flow between scripts']['detail'])
        resnet = titles['Model overview of ResNet']                 # composes BasicBlock: high level
        self.assertEqual((resnet['level'], resnet['pattern']), ('high', 'cnn'))
        self.assertIn('Sequential[BasicBlock x2]', resnet['detail'])
        block = titles['Architecture of BasicBlock']
        self.assertEqual(block['detail'], 'Conv2d -> BatchNorm2d -> relu -> Conv2d (+ residual)')  # run order
        self.assertEqual(resnet['detail'], 'Conv2d -> Sequential[BasicBlock x2] -> Linear')
        self.assertEqual(titles['Architecture of Encoder']['pattern'], 'transformer')
        self.assertIn('zero grads', titles['Training loop train()']['detail'])
        self.assertIn('early stop', titles['Training loop train()']['detail'])
        pgm = titles['Graphical model model()']
        self.assertEqual(pgm['detail'], 'latent: mu, sigma; observed: y; plates: N')
        self.assertIn("einsum 'bhqd,bhkd->bhqk'", titles['Tensor shapes in attention()']['detail'])
        self.assertEqual(titles['State machine Phase']['detail'], 'WARMUP, RUN, COOLDOWN')
        self.assertIn('Iterative algorithm solve()', titles)
        self.assertIn('explore.ipynb cell 2', titles['Time-stepping scheme in step()']['evidence'])
        self.assertIn('Plot of results/metrics.csv', titles)
        self.assertTrue(all(i['level'] == 'high' for i in high))


if __name__ == '__main__':
    unittest.main()
