/**
 * Score Calculation Functions for Frontend
 * 
 * These functions calculate overall scores from category scores using weighted averages.
 * The weighting is based on tier (priority) and severity of questions.
 */

/**
 * Calculate Overall Score from Category Scores
 * 
 * Formula: Weighted average of all category scores
 * - Each category has a score (0-100) and a total_weight
 * - Overall Score = sum(category_score × category_weight) / sum(category_weights) × 100
 * 
 * Example:
 *   Category A: score=80%, weight=15
 *   Category B: score=50%, weight=10
 *   Overall = (80×15 + 50×10) / (15+10) × 100 = (1200 + 500) / 25 × 100 = 68%
 * 
 * @param {Array} categoryScores - Array of category score objects
 *   Each object should have: {category: string, score: number, total_weight: number}
 * @returns {number} Overall score (0-100, rounded)
 */
function calculateOverallScore(categoryScores) {
    if (!categoryScores || categoryScores.length === 0) {
        return 0;
    }
    
    let totalWeightedScore = 0;
    let totalWeight = 0;
    
    categoryScores.forEach(cat => {
        const score = cat.score || 0; // Score is 0-100
        const weight = cat.total_weight || 1; // Weight from tier × severity
        
        // Add weighted score contribution
        // Convert score to 0-1 scale, multiply by weight, then sum
        totalWeightedScore += (score / 100) * weight;
        totalWeight += weight;
    });
    
    if (totalWeight === 0) {
        return 0;
    }
    
    // Calculate weighted average and convert back to 0-100 scale
    const overallScore = (totalWeightedScore / totalWeight) * 100;
    return Math.round(overallScore);
}

/**
 * Calculate Overall Score per Stage (Awareness, Consideration, Conversion)
 * Groups categories by stage and calculates weighted average per stage
 * 
 * @param {Array} categoryScores - Array of category score objects
 * @param {Array} questions - Array of question objects with category field
 * @returns {Object} Object with stage scores
 *   {awareness: number, consideration: number, conversion: number}
 */
function calculateStageScores(categoryScores, questions) {
    const stages = {
        'Awareness': [],
        'Consideration': [],
        'Conversion': []
    };
    
    // Map categories to stages based on questions
    const categoryToStage = {};
    questions.forEach(q => {
        const category = q.bar_chart_category;
        const stage = q.category; // This is the stage (Awareness/Consideration/Conversion)
        if (stage && stages[stage]) {
            categoryToStage[category] = stage;
        }
    });
    
    // Group category scores by stage
    categoryScores.forEach(cat => {
        const stage = categoryToStage[cat.category];
        if (stage && stages[stage]) {
            stages[stage].push(cat);
        }
    });
    
    // Calculate score for each stage
    const result = {};
    Object.keys(stages).forEach(stage => {
        result[stage.toLowerCase()] = calculateOverallScore(stages[stage]);
    });
    
    return result;
}

/**
 * Calculate category score from questions manually (if category_scores not provided)
 * 
 * This replicates the backend calculation:
 * - Tier weight: Tier 1 = 3, Tier 2 = 2, Tier 3 = 1
 * - Severity weight: 5 = 5, 4 = 4, 3 = 3, 2 = 2, 1 = 1
 * - Combined weight = tier_weight × severity_weight
 * - Question score = weight × (1 if pass, 0 if fail)
 * - Category score = sum(weighted_scores) / sum(weights) × 100
 * 
 * @param {Array} questions - Array of question objects
 * @returns {Array} Array of category score objects
 */
function calculateCategoryScoresFromQuestions(questions) {
    const tierWeights = { 1: 3, 2: 2, 3: 1 };
    const categories = {};
    
    questions.forEach(q => {
        const category = q.bar_chart_category || 'Unknown';
        
        if (!categories[category]) {
            categories[category] = {
                weightedScore: 0,
                totalWeight: 0,
                totalQuestions: 0
            };
        }
        
        const tier = q.tier || 1;
        const severity = q.severity || 1;
        const tierWeight = tierWeights[tier] || 1;
        const severityWeight = severity;
        const combinedWeight = tierWeight * severityWeight;
        
        const questionScore = q.result === 'pass' ? 1.0 : 0.0;
        const weightedScore = combinedWeight * questionScore;
        
        categories[category].weightedScore += weightedScore;
        categories[category].totalWeight += combinedWeight;
        categories[category].totalQuestions++;
    });
    
    // Convert to score format
    const categoryScores = [];
    Object.keys(categories).forEach(category => {
        const data = categories[category];
        const score = data.totalWeight > 0 
            ? (data.weightedScore / data.totalWeight) * 100 
            : 0;
        
        categoryScores.push({
            category: category,
            score: parseFloat(score.toFixed(2)),
            total_questions: data.totalQuestions,
            total_weight: parseFloat(data.totalWeight.toFixed(2))
        });
    });
    
    return categoryScores.sort((a, b) => b.score - a.score);
}

// Export for use in modules (if using ES6 modules)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        calculateOverallScore,
        calculateStageScores,
        calculateCategoryScoresFromQuestions
    };
}
