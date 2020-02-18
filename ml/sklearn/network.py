import torch
import torchvision
import torchvision.transforms as transforms
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
train_set = torchvision.datasets.FashionMNIST(
    root='./data/FashionMNIST', train=True, download=True, transform=transforms.Compose([
        transforms.ToTensor()
    ])
)
torch.set_grad_enabled(True)  # Already on by default
torch.set_printoptions(linewidth=120)  # Display options for output


def get_num_correct(preds, labels):
    return preds.argmax(dim=1).eq(labels).sum().item()


class Network(nn.Module):
    def __init__(self):
        super(Network, self).__init__()
        self.conv1 = nn.Conv2d(in_channels=1, out_channels=6, kernel_size=5)
        self.conv2 = nn.Conv2d(in_channels=6, out_channels=12, kernel_size=5)

        self.fc1 = nn.Linear(in_features=12*4*4, out_features=120)
        self.fc2 = nn.Linear(in_features=120, out_features=60)
        self.out = nn.Linear(in_features=60, out_features=10)

    def forward(self, t):
        # implement the forward pass

        # input layer
        t = t

        # hidden conv layer
        t = self.conv1(t)
        t = F.relu(t)
        t = F.max_pool2d(t, kernel_size=2, stride=2)

        # hidden conv layer
        t = self.conv2(t)
        t = F.relu(t)
        t = F.max_pool2d(t, kernel_size=2, stride=2)

        # hiddden Linear layer
        t = t.reshape(-1, 12*4*4)
        t = self.fc1(t)
        t = F.relu(t)

        # hidden Linear layer

        t = self.fc2(t)
        t = F.relu(t)

        # output layer
        t = self.out(t)
        t = F.softmax(t, dim=1)

        return t


network = Network()
train_loader = torch.utils.data.DataLoader(train_set, batch_size=100)
optimizer = optim.Adam(network.parameters(), lr=0.01)

total_loss = 0
total_correct = 0

for batch in train_loader:  # get batch
    images, labels = batch
    preds = network(images)
    # Calculate the Loss
    loss = F.cross_entropy(preds, labels)

    optimizer.zero_grad()
    loss.backward()  # Calculate Gradients
    optimizer.step()  # Update Weights

    total_loss += loss.item()
    total_correct += get_num_correct(preds, labels)

print("epoch:", 0, "total_correct:", total_correct, "loss:", total_loss)

total_correct/len(train_set)
