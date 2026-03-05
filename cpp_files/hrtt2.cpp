// heart_area.cpp
#include <iostream>
#include <vector>
#include <cmath>
#include <random>
#include <chrono>
#include <iomanip>

// Calculate area score between two arrays.
// Repeats normal_arr to match length of anx_arr, computes absolute difference,
// integrates using trapezoidal rule, and returns area / N (normalized).
double calculateAreaScore(const std::vector<double>& normal_arr,
                          const std::vector<double>& anx_arr)
{
    if (normal_arr.empty() || anx_arr.empty()) return 0.0;

    const size_t N = anx_arr.size();
    const size_t N1 = normal_arr.size();

    // If normal_arr length is 1, repeating it is trivial; otherwise map by modulo.
    auto get_normal_at = [&](size_t idx) -> double {
        return normal_arr[idx % N1];
    };

    // Trapezoidal integration of absolute difference
    double area = 0.0;
    if (N == 1) return 0.0; // nothing to integrate

    double prev_diff = std::abs(anx_arr[0] - get_normal_at(0));
    for (size_t i = 1; i < N; ++i) {
        double cur_diff = std::abs(anx_arr[i] - get_normal_at(i));
        area += (prev_diff + cur_diff) / 2.0; // dx = 1
        prev_diff = cur_diff;
    }

    return area / static_cast<double>(N);
}

// Helper: generate a "normal" heart rate sequence (gentle variations)
std::vector<double> generate_fake_heart_rate(size_t length,
                                             double base = 70.0,
                                             unsigned int seed = 0)
{
    if (seed == 0) seed = static_cast<unsigned int>(
        std::chrono::high_resolution_clock::now().time_since_epoch().count());

    std::mt19937 rng(seed);
    std::normal_distribution<double> noise(0.0, 1.5); // small random jitter

    std::vector<double> out;
    out.reserve(length);

    for (size_t i = 0; i < length; ++i) {
        // slow sinusoidal drift + small Gaussian noise
        double drift = 1.5 * std::sin(2.0 * M_PI * static_cast<double>(i) / 40.0);
        double hr = base + drift + noise(rng);
        out.push_back(hr);
    }
    return out;
}

// Helper: generate an "anxiety" heart rate sequence (elevated, more jitter & occasional spikes)
std::vector<double> generate_anxiety_heart_rate(size_t length,
                                                double base = 85.0,
                                                unsigned int seed = 0)
{
    if (seed == 0) seed = static_cast<unsigned int>(
        std::chrono::high_resolution_clock::now().time_since_epoch().count() + 12345);

    std::mt19937 rng(seed);
    std::normal_distribution<double> noise(0.0, 2.5); // larger jitter
    std::uniform_real_distribution<double> spike_chance(0.0, 1.0);
    std::uniform_real_distribution<double> spike_size(5.0, 15.0);

    std::vector<double> out;
    out.reserve(length);

    for (size_t i = 0; i < length; ++i) {
        // slightly faster oscillation and random noise
        double drift = 3.0 * std::sin(2.0 * M_PI * static_cast<double>(i) / 20.0);
        double hr = base + drift + noise(rng);

        // occasional spikes representing panic bursts
        if (spike_chance(rng) < 0.03) { // ~3% chance per sample
            hr += spike_size(rng);
        }

        out.push_back(hr);
    }
    return out;
}

int main()
{
    // replicate the Python example sizes
    const size_t N1 = 50;   // length of normal_arr
    const size_t N  = 224;  // length of anx_arr

    // Generate example signals
    auto normal_hr = generate_fake_heart_rate(N1);
    auto anx_hr    = generate_anxiety_heart_rate(N);

    // Compute area score
    double score = calculateAreaScore(normal_hr, anx_hr);

    // Print results
    std::cout << std::fixed << std::setprecision(6);
    std::cout << "Normal length (N1): " << N1 << "\n";
    std::cout << "Anxiety length (N): " << N << "\n";
    std::cout << "Area between curves (normalized): " << score << "\n";

    // Optional: print a small sample of values (first 10) for quick inspection
    std::cout << "\nFirst 10 anxiety HR samples: ";
    for (size_t i = 0; i < std::min<size_t>(10, anx_hr.size()); ++i) {
        std::cout << anx_hr[i] << (i+1 < 10 ? ", " : "\n");
    }

    std::cout << "First 10 repeated normal HR samples (mapped): ";
    for (size_t i = 0; i < std::min<size_t>(10, anx_hr.size()); ++i) {
        std::cout << normal_hr[i % normal_hr.size()] << (i+1 < 10 ? ", " : "\n");
    }

    return 0;
}