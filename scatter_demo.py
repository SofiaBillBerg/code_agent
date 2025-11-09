# Demo scatter plot
import matplotlib.pyplot as plt
import numpy as np


def create_scatter_plot():
    """Generates and saves a random scatter plot."""
    np.random.seed(0)
    x = np.random.randn(100)
    y = np.random.randn(100)

    plt.figure()  # Create a new figure
    plt.scatter(x, y)
    plt.title("Random Scatter Plot")
    plt.xlabel("X-axis")
    plt.ylabel("Y-axis")
    plt.grid(True)
    plt.savefig("scatter_plot.png")
    print("Scatter plot saved to scatter_plot.png")
    return "scatter_plot.png"


if __name__ == "__main__":
    create_scatter_plot()
    plt.show()
