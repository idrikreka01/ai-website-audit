// JavaScript function to process report JSON and prepare data for bar charts
// Use this with your HTML report

/**
 * Process audit report JSON and group questions by bar_chart_category
 * Uses weighted scoring based on tier (priority) and severity.
 * 
 * Weighting formula:
 * - Tier weight: Tier 1 = 3, Tier 2 = 2, Tier 3 = 1
 * - Severity weight: 5 = 5, 4 = 4, 3 = 3, 2 = 2, 1 = 1
 * - Combined weight = tier_weight * severity_weight
 * - Question score = weight * (1 if pass, 0 if fail)
 * - Category score = sum(weighted_scores) / sum(weights) * 100
 * 
 * @param {Object} reportData - The JSON response from GET /audits/{session_id}/report
 * @returns {Object} Grouped data with weighted scores per category
 */
function processBarChartData(reportData) {
    // If category_scores already exist in report, use them (pre-calculated)
    if (reportData.category_scores && reportData.category_scores.length > 0) {
        return {
            chartData: reportData.category_scores.map(cat => ({
                category: cat.category,
                score: cat.score,
                totalQuestions: cat.total_questions,
                totalWeight: cat.total_weight
            }))
        };
    }
    
    // Otherwise calculate manually
    const tierWeights = { 1: 3, 2: 2, 3: 1 };
    const categories = {};
    
    reportData.questions.forEach(question => {
        const category = question.bar_chart_category || 'Unknown';
        
        if (!categories[category]) {
            categories[category] = {
                weightedScore: 0,
                totalWeight: 0,
                pass: 0,
                fail: 0,
                total: 0,
                questions: []
            };
        }
        
        const tier = question.tier || 1;
        const severity = question.severity || 1;
        const tierWeight = tierWeights[tier] || 1;
        const severityWeight = severity;
        const combinedWeight = tierWeight * severityWeight;
        
        const questionScore = question.result === 'pass' ? 1.0 : 0.0;
        const weightedScore = combinedWeight * questionScore;
        
        categories[category].weightedScore += weightedScore;
        categories[category].totalWeight += combinedWeight;
        categories[category].total++;
        
        if (question.result === 'pass') {
            categories[category].pass++;
        } else {
            categories[category].fail++;
        }
        
        categories[category].questions.push({
            question_id: question.question_id,
            tier: tier,
            severity: severity,
            weight: combinedWeight,
            result: question.result
        });
    });
    
    const chartData = Object.keys(categories).map(category => {
        const data = categories[category];
        const score = data.totalWeight > 0 
            ? (data.weightedScore / data.totalWeight) * 100 
            : 0;
        
        return {
            category: category,
            score: parseFloat(score.toFixed(2)),
            totalQuestions: data.total,
            totalWeight: parseFloat(data.totalWeight.toFixed(2)),
            pass: data.pass,
            fail: data.fail
        };
    }).sort((a, b) => b.score - a.score);
    
    return {
        categories: categories,
        chartData: chartData
    };
}

/**
 * Create bar chart with weighted scores from report data
 * Uses weighted scoring based on tier (priority) and severity
 */
function createBarChartFromReport(reportData) {
    const processed = processBarChartData(reportData);
    const chartData = processed.chartData;
    
    const ctx = document.getElementById('barChart').getContext('2d');
    
    // Color based on score: green (80+), yellow (50-79), red (<50)
    const getColor = (score) => {
        if (score >= 80) return 'rgba(40, 167, 69, 0.7)'; // Green
        if (score >= 50) return 'rgba(255, 193, 7, 0.7)';  // Yellow
        return 'rgba(220, 53, 69, 0.7)'; // Red
    };
    
    const getBorderColor = (score) => {
        if (score >= 80) return 'rgba(40, 167, 69, 1)';
        if (score >= 50) return 'rgba(255, 193, 7, 1)';
        return 'rgba(220, 53, 69, 1)';
    };
    
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: chartData.map(c => c.category),
            datasets: [
                {
                    label: 'Weighted Score %',
                    data: chartData.map(c => c.score),
                    backgroundColor: chartData.map(c => getColor(c.score)),
                    borderColor: chartData.map(c => getBorderColor(c.score)),
                    borderWidth: 1
                }
            ]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100,
                    ticks: {
                        callback: function(value) {
                            return value + '%';
                        }
                    }
                },
                x: {
                    ticks: {
                        maxRotation: 45,
                        minRotation: 45
                    }
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const category = chartData[context.dataIndex];
                            return [
                                `Score: ${category.score}%`,
                                `Questions: ${category.totalQuestions}`,
                                `Pass: ${category.pass || 0}, Fail: ${category.fail || 0}`,
                                `Total Weight: ${category.totalWeight}`
                            ];
                        }
                    }
                },
                legend: {
                    display: false
                }
            }
        }
    });
}

/**
 * Fetch report data from API and create chart
 */
async function loadReportAndCreateChart(sessionId) {
    try {
        const response = await fetch(`http://localhost:8000/audits/${sessionId}/report`);
        const reportData = await response.json();
        
        createBarChartFromReport(reportData);
        
        return reportData;
    } catch (error) {
        console.error('Error loading report:', error);
        throw error;
    }
}

// Usage example:
// loadReportAndCreateChart('f897f03f-7404-443a-b497-3a9421463c16');
