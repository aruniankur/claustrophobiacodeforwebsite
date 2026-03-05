#include <iostream>
#include <random>
#include <algorithm>

// Parameter limits
const double t_min = 5,  t_max = 50;
const double I_min = 80, I_max = 110;
const double S_min = 60, S_max = 80;

// Random noise generator
std::random_device rd;
std::mt19937 gen(rd());
std::uniform_real_distribution<double> noise(-0.02, 0.02);

double clamp(double x)
{
    return std::max(0.0, std::min(1.0, x));
}

void scoreChanger(double &t, double &I, double &S,
                  double area, double threshold, double lr)
{
    // Normalize to [0,1]
    t = (t - t_min) / (t_max - t_min);
    I = (I - I_min) / (I_max - I_min);
    S = (S - S_min) / (S_max - S_min);

    // Error
    double error = area - threshold;

    // Feedback control
    t -= lr * error;
    I -= lr * error;
    S += lr * error;

    // Add small noise
    t += noise(gen);
    I += noise(gen);
    S += noise(gen);

    // Clamp to valid range
    t = clamp(t);
    I = clamp(I);
    S = clamp(S);

    // De-normalize
    t = t * (t_max - t_min) + t_min;
    I = I * (I_max - I_min) + I_min;
    S = S * (S_max - S_min) + S_min;
}

int main()
{
    double t = 10;
    double I = 90;
    double S = 70;

    double area = 1.1;
    double threshold = 1.0;
    double lr = 0.1;

    for (int i = 0; i < 10; i++)
    {
        scoreChanger(t, I, S, area, threshold, lr);

        std::cout << "Step " << i
                  << " | t=" << t
                  << " I=" << I
                  << " S=" << S << std::endl;
    }
}
