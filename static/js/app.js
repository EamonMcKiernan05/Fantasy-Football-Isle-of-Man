/** Fantasy Football Isle of Man - Frontend Application */

// State
const state = {
    user: JSON.parse(localStorage.getItem('ff_iom_user') || 'null'),
    team: null,
    gameweek: null,
    leaderboard: [],
    leagues: [],
    transferPlayerOut: null,
    formation: '4-3-3',
};

// API helpers
async function api(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : endpoint;
    const defaults = {
        headers: { 'Content-Type': 'application/json' },
    };

    const resp = await fetch(url, { ...defaults, ...options });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Request failed' }));
        throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    return resp.json();
}

// Navigation
function showPage(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

    const target = document.getElementById(`page-${page}`);
    if (target) target.classList.add('active');

    const link = document.querySelector(`.nav-link[data-page="${page}"]`);
    if (link) link.classList.add('active');

    switch(page) {
        case 'home': loadHome(); break;
        case 'my-team': loadMyTeam(); break;
        case 'transfers': loadTransfers(); break;
        case 'players': loadPlayers(); break;
        case 'gameweeks': loadGameweeks(); break;
        case 'leaderboard': loadLeaderboard(); break;
        case 'leagues': loadLeagues(); break;
        case 'history': loadHistory(); break;
    }
}

document.querySelectorAll('.nav-link').forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();
        showPage(link.dataset.page);
    });
});

// Toast
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// Auth
async function handleRegister(e) {
    e.preventDefault();
    const username = document.getElementById('reg-username').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;
    const teamName = document.getElementById('reg-team-name').value;

    try {
        const user = await api('/api/users/register', {
            method: 'POST',
            body: JSON.stringify({ username, email, password }),
        });

        await api(`/api/users/${user.id}/team/create`, {
            method: 'POST',
            body: JSON.stringify({ team_name: teamName }),
        });

        state.user = user;
        localStorage.setItem('ff_iom_user', JSON.stringify(user));
        updateNav();
        showToast(`Welcome ${username}! Team "${teamName}" created.`);
        showPage('my-team');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function handleLogin(e) {
    e.preventDefault();
    const username = document.getElementById('login-username').value;
    const password = document.getElementById('login-password').value;

    try {
        const user = await api('/api/users/login', {
            method: 'POST',
            body: new URLSearchParams({ username, password }),
        });

        state.user = user;
        localStorage.setItem('ff_iom_user', JSON.stringify(user));
        updateNav();
        showToast(`Welcome back ${username}!`);
        showPage('my-team');
    } catch (err) {
        showToast('Invalid credentials', 'error');
    }
}

function logout() {
    state.user = null;
    state.team = null;
    localStorage.removeItem('ff_iom_user');
    updateNav();
    showPage('home');
}

function updateNav() {
    const navUser = document.getElementById('nav-user');
    const navAuth = document.getElementById('nav-auth');

    if (state.user) {
        navUser.style.display = 'flex';
        navAuth.style.display = 'none';
        document.getElementById('nav-username').textContent = state.user.username;
    } else {
        navUser.style.display = 'none';
        navAuth.style.display = 'flex';
    }
}

// HOME
async function loadHome() {
    const banner = document.getElementById('gw-banner');
    if (!banner) return;

    try {
        const data = await api('/api/gameweeks/current');
        if (data.gameweek) {
            const gw = data.gameweek;
            const deadline = new Date(gw.deadline).toLocaleString();
            const remaining = data.deadline_remaining || 0;
            const hours = Math.floor(remaining / 3600);
            const mins = Math.floor((remaining % 3600) / 60);

            banner.innerHTML = `
                <div>
                    <h3>Gameweek ${gw.number}</h3>
                    <p>${gw.fixtures ? gw.fixtures.length : 0} fixtures</p>
                </div>
                <div class="gw-deadline">
                    Deadline: ${deadline}
                    ${gw.closed
                        ? '<span style="padding:0.3rem 0.75rem;border-radius:4px;background:var(--red);color:white;">Closed</span>'
                        : `<span style="padding:0.3rem 0.75rem;border-radius:4px;background:var(--green);color:white;">Open - ${hours}h ${mins}m remaining</span>`
                    }
                </div>
            `;
        } else {
            banner.innerHTML = '<p>No active gameweek. Sync fixtures to start.</p>';
        }
    } catch (err) {
        banner.innerHTML = '<p>Could not load gameweek data.</p>';
    }
}

// MY TEAM
async function loadMyTeam() {
    if (!state.user) {
        showToast('Please login first', 'error');
        showPage('login');
        return;
    }

    try {
        state.team = await api(`/api/users/${state.user.id}/team`);
        renderMyTeam();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderMyTeam() {
    const team = state.team;
    if (!team) return;

    document.getElementById('team-name').textContent = team.name;
    document.getElementById('team-points').textContent = team.total_points;
    document.getElementById('team-budget').textContent = team.budget_remaining.toFixed(1);
    document.getElementById('team-transfers').textContent = team.free_transfers;

    // Nav points
    const navPoints = document.getElementById('nav-points');
    if (navPoints) navPoints.textContent = `${team.total_points} pts`;

    // Render formation
    renderPitch(team.squad);
    renderBench(team.squad);
    renderChips(team.chip_status);
    renderTeamStats(team);
}

function renderPitch(squad) {
    const container = document.getElementById('pitch-players');
    if (!container) return;
    container.innerHTML = '';

    const formation = state.formation || '4-3-3';
    const positions = getFormationPositions(formation);

    const starters = squad.filter(p => p.is_starting);

    // Sort starters by position
    const gk = starters.filter(p => p.player.position === 'GK');
    const defs = starters.filter(p => p.player.position === 'DEF');
    const mids = starters.filter(p => p.player.position === 'MID');
    const fwds = starters.filter(p => p.player.position === 'FWD');

    const allStarters = [...gk, ...defs, ...mids, ...fwds];

    positions.forEach((pos, i) => {
        if (i >= allStarters.length) return;
        const sp = allStarters[i];
        if (!sp || !sp.player) return;

        const playerDiv = document.createElement('div');
        playerDiv.className = 'pitch-player';
        playerDiv.style.left = pos.x + '%';
        playerDiv.style.top = pos.y + '%';

        const circleClass = sp.is_captain ? 'captain' : (sp.is_vice_captain ? 'vice' : '');
        const badge = sp.is_captain ? 'C' : (sp.is_vice_captain ? 'VC' : '');

        const posColor = {
            'GK': 'var(--gk)',
            'DEF': 'var(--def)',
            'MID': 'var(--mid)',
            'FWD': 'var(--fwd)',
        }[sp.player.position] || 'var(--text-muted)';

        playerDiv.innerHTML = `
            <div class="player-circle ${circleClass}" style="background:${posColor}">
                ${badge || sp.player.position}
            </div>
            <div class="player-name">${sp.player.name}</div>
            <div class="player-pts">${sp.total_points || 0}</div>
        `;

        playerDiv.onclick = () => setCaptainFromPitch(sp);
        container.appendChild(playerDiv);
    });
}

function renderBench(squad) {
    const container = document.getElementById('bench-grid');
    if (!container) return;
    container.innerHTML = '';

    const bench = squad.filter(p => !p.is_starting)
        .sort((a, b) => (a.bench_priority || 99) - (b.bench_priority || 99));

    bench.forEach((sp, i) => {
        if (!sp.player) return;
        const div = document.createElement('div');
        div.className = `bench-player ${sp.was_autosub ? 'autosub' : ''}`;
        div.innerHTML = `
            <span class="pos-badge pos-${sp.player.position}">${sp.player.position}</span>
            <span>${sp.player.name}</span>
            <span style="margin-left:auto;color:var(--green)">${sp.total_points || 0}</span>
            ${sp.was_autosub ? '<span style="color:var(--yellow);font-size:0.75rem;margin-left:0.5rem;">SUB</span>' : ''}
        `;
        container.appendChild(div);
    });
}

function renderChips(chipStatus) {
    const container = document.getElementById('chips-grid');
    if (!container) return;

    const currentHalf = chipStatus.current_half || 'first';
    const halfKey = currentHalf === 'first' ? 'first_half' : 'second_half';

    const chips = [
        {
            id: 'wildcard',
            name: `Wildcard (${currentHalf === 'first' ? '1st' : '2nd'} Half)`,
            desc: currentHalf === 'first' ? 'Unlimited transfers. GW 1-19.' : 'Unlimited transfers. GW 20-38.',
            used: chipStatus[`${halfKey}_used`] || false,
            available: chipStatus[`${halfKey}_available`] || true,
            action: 'wildcard',
            icon: '🔄',
        },
        {
            id: 'free_hit',
            name: `Free Hit (${currentHalf === 'first' ? '1st' : '2nd'} Half)`,
            desc: 'Temporary squad for 1 GW.',
            used: chipStatus[`free_hit_${halfKey}_used`] || false,
            available: chipStatus[`free_hit_${halfKey}_available`] || true,
            action: 'free_hit',
            icon: '⚡',
        },
        {
            id: 'bench_boost',
            name: `Bench Boost (${currentHalf === 'first' ? '1st' : '2nd'} Half)`,
            desc: 'All 15 players score.',
            used: chipStatus[`bench_boost_${halfKey}_used`] || false,
            available: chipStatus[`bench_boost_${halfKey}_available`] || true,
            action: 'bench_boost',
            icon: '📈',
        },
        {
            id: 'triple_captain',
            name: `Triple Captain (${currentHalf === 'first' ? '1st' : '2nd'} Half)`,
            desc: 'Captain gets 3x points.',
            used: chipStatus[`triple_captain_${halfKey}_used`] || false,
            available: chipStatus[`triple_captain_${halfKey}_available`] || true,
            action: 'triple_captain',
            icon: '⭐',
        },
    ];

    container.innerHTML = chips.map(chip => {
        const isActive = chipStatus.active_chip === chip.action;
        const statusClass = chip.used ? 'used' : (isActive ? 'active' : 'available');
        const statusText = chip.used ? 'USED' : (isActive ? 'ACTIVE' : (chip.available ? 'Available' : 'Not Available'));
        const statusColor = chip.used ? 'var(--red)' : (isActive ? 'var(--purple)' : (chip.available ? 'var(--green)' : 'var(--text-muted)'));

        return `
            <div class="chip-card ${statusClass}">
                <div style="font-size:1.5rem;">${chip.icon}</div>
                <h4>${chip.name}</h4>
                <p>${chip.desc}</p>
                <span style="color:${statusColor};font-size:0.75rem;font-weight:bold;">${statusText}</span>
                ${!chip.used && chip.available && !isActive ?
                    `<button class="btn btn-sm btn-primary" onclick="activateChip('${chip.action}')">Activate</button>` :
                    (isActive ? `<button class="btn btn-sm btn-warning" onclick="cancelChip('${chip.action}')">Cancel</button>` : '')
                }
            </div>
        `;
    }).join('');
}

function renderTeamStats(team) {
    const container = document.getElementById('team-stats');
    if (!container || !team.squad) return;

    const squad = team.squad;
    const totalSquadPoints = squad.reduce((sum, sp) => sum + (sp.total_points || 0), 0);
    const avgPrice = squad.reduce((sum, sp) => sum + (sp.player?.price || 0), 0) / squad.length;
    const form = team.total_points; // Simplified

    container.innerHTML = `
        <div class="stat-card">
            <div class="stat-value">${team.total_points}</div>
            <div class="stat-label">Total Points</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">£${team.budget_remaining.toFixed(1)}m</div>
            <div class="stat-label">Budget</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${team.free_transfers}</div>
            <div class="stat-label">Free Transfers</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">${team.overall_rank || '-'}</div>
            <div class="stat-label">Overall Rank</div>
        </div>
    `;
}

async function activateChip(chip) {
    if (!state.user) return;
    try {
        if (chip === 'wildcard') {
            showToast('Use wildcard through the Transfers page', 'info');
            showPage('transfers');
            return;
        }
        await api(`/api/users/${state.user.id}/team/chip`, {
            method: 'POST',
            body: JSON.stringify({ chip, cancel: false }),
        });
        showToast(`${chip.replace('_', ' ').toUpperCase()} activated!`);
        loadMyTeam();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function cancelChip(chip) {
    if (!state.user) return;
    try {
        await api(`/api/users/${state.user.id}/team/chip`, {
            method: 'POST',
            body: JSON.stringify({ chip, cancel: true }),
        });
        showToast(`${chip.replace('_', ' ').toUpperCase()} cancelled`);
        loadMyTeam();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function getFormationPositions(formation) {
    const [def, mid, fwd] = formation.split('-').map(Number);
    const positions = [];

    // GK at bottom
    positions.push({ x: 50, y: 90 });

    // DEF line
    const defY = 70;
    for (let i = 0; i < def; i++) {
        positions.push({ x: 20 + (i * 60 / (def - 1 || 1)), y: defY });
    }

    // MID line
    const midY = 45;
    for (let i = 0; i < mid; i++) {
        positions.push({ x: 15 + (i * 70 / (mid - 1 || 1)), y: midY });
    }

    // FWD line
    const fwdY = 20;
    for (let i = 0; i < fwd; i++) {
        positions.push({ x: 25 + (i * 50 / (fwd - 1 || 1)), y: fwdY });
    }

    return positions;
}

function changeFormation() {
    state.formation = document.getElementById('formation-select').value;
    renderPitch(state.team.squad);
}

async function setCaptainFromPitch(sp) {
    if (!state.user) return;

    // Cycle: select captain -> set vice to another player
    const vc = state.team.squad.find(p => !p.is_captain && p.id !== sp.id);
    try {
        await api(`/api/users/${state.user.id}/team/captain`, {
            method: 'PUT',
            body: JSON.stringify({
                captain_id: sp.id,
                vice_captain_id: vc ? vc.id : null,
            }),
        });
        showToast(`${sp.player.name} is now captain${vc ? `, ${vc.player.name} is vice` : ''}`);
        loadMyTeam();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// TRANSFERS
async function loadTransfers() {
    if (!state.user) {
        showPage('login');
        return;
    }

    try {
        const status = await api(`/api/transfers/status/${state.user.id}`);
        document.getElementById('transfer-free').textContent = status.free_transfers;
        document.getElementById('transfer-budget').textContent = status.budget_remaining.toFixed(1);

        // Wildcard status
        const wildcardEl = document.getElementById('wildcard-status');
        if (wildcardEl) {
            const firstAvail = status.wildcard_first_half_available;
            const secondAvail = status.wildcard_second_half_available;
            wildcardEl.textContent = (firstAvail || secondAvail) ? 'Available' : 'Both Used';
        }

        // Active chip
        const activeChipEl = document.getElementById('active-chip-display');
        if (activeChipEl && status.active_chip) {
            activeChipEl.textContent = `Active: ${status.active_chip.replace('_', ' ').toUpperCase()}`;
            activeChipEl.style.display = 'block';
        }

        searchTransferPlayers();
    } catch (err) {
        // Ignore status errors
    }
}

async function searchTransferPlayers() {
    if (!state.user) return;

    const query = document.getElementById('transfer-search-input')?.value || '';
    const position = document.getElementById('transfer-position-filter')?.value || '';

    try {
        const params = new URLSearchParams();
        if (query) params.set('search', query);
        if (position) params.set('position', position);

        const players = await api(`/api/players/?${params}`);
        renderTransferList(players);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderTransferList(players) {
    const container = document.getElementById('transfer-results');
    if (!container) return;

    const squadPlayerIds = new Set(
        (state.team?.squad || []).map(sp => sp.player_id)
    );

    container.innerHTML = players.map(p => {
        const inSquad = squadPlayerIds.has(p.id);
        const priceChange = p.price_change || 0;
        const priceChangeClass = priceChange > 0 ? 'price-up' : (priceChange < 0 ? 'price-down' : '');
        const priceChangeIcon = priceChange > 0 ? '↑' : (priceChange < 0 ? '↓' : '');

        return `
            <div class="player-card ${inSquad ? 'in-squad' : ''}"
                 onclick="${inSquad ? `selectPlayerOut(${p.id})` : `executeTransfer(${p.id})`}">
                <span class="pos-badge pos-${p.position}">${p.position}</span>
                <div class="player-info">
                    <div class="player-name">${p.name}</div>
                    <div class="player-team">${p.team_id ? 'Team ' + p.team_id : ''}</div>
                </div>
                <div class="player-stats">
                    <span class="player-price ${priceChangeClass}">${p.price.toFixed(1)}m ${priceChangeIcon}</span>
                    ${inSquad ? '<span style="color:var(--green)">OWNED</span>' : ''}
                    ${p.form ? `<span style="color:var(--yellow)">Form: ${p.form}</span>` : ''}
                    ${p.ict_index ? `<span>ICT: ${p.ict_index}</span>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

function selectPlayerOut(playerId) {
    if (!state.team) return;
    const sp = state.team.squad.find(s => s.player_id === playerId);
    if (!sp) return;

    state.transferPlayerOut = sp;
    const selectedDiv = document.getElementById('transfer-selected');
    selectedDiv.style.display = 'flex';
    document.getElementById('selected-out').innerHTML = `
        <span class="pos-badge pos-${sp.player.position}">${sp.player.position}</span>
        <strong>${sp.player.name}</strong>
        <span>${sp.player.price.toFixed(1)}m</span>
        ${sp.purchase_price ? `<span style="font-size:0.75rem;color:var(--text-muted)">Bought: ${sp.purchase_price.toFixed(1)}m</span>` : ''}
    `;
}

async function executeTransfer(playerInId) {
    if (!state.user || !state.transferPlayerOut) {
        showToast('Select a player to swap out first', 'error');
        return;
    }

    try {
        const result = await api(`/api/transfers/`, {
            method: 'POST',
            body: JSON.stringify({
                player_in_id: playerInId,
                player_out_id: state.transferPlayerOut.player_id,
                user_id: state.user.id,
            }),
        });

        showToast(`Transfer complete! ${result.transfer_cost || 'Free'}`);
        state.transferPlayerOut = null;
        const selectedDiv = document.getElementById('transfer-selected');
        if (selectedDiv) selectedDiv.style.display = 'none';
        loadMyTeam();
        loadTransfers();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// PLAYERS
async function loadPlayers() {
    const query = document.getElementById('player-search')?.value || '';
    const position = document.getElementById('player-position')?.value || '';
    const sortBy = document.getElementById('player-sort')?.value || 'goals';

    try {
        const params = new URLSearchParams();
        if (query) params.set('search', query);
        if (position) params.set('position', position);
        params.set('order_by', sortBy);

        const players = await api(`/api/players/?${params}`);
        renderPlayerList(players);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderPlayerList(players) {
    const container = document.getElementById('players-container');
    if (!container) return;

    const squadPlayerIds = new Set(
        (state.team?.squad || []).map(sp => sp.player_id)
    );

    container.innerHTML = players.map(p => {
        const inSquad = squadPlayerIds.has(p.id);
        const priceChange = p.price_change || 0;
        const priceChangeIcon = priceChange > 0 ? '↑' : (priceChange < 0 ? '↓' : '');

        return `
            <div class="player-card ${inSquad ? 'in-squad' : ''}">
                <span class="pos-badge pos-${p.position}">${p.position}</span>
                <div class="player-info">
                    <div class="player-name">${p.name}</div>
                    <div class="player-team">${p.team_id ? 'Team ' + p.team_id : ''}</div>
                </div>
                <div class="player-stats">
                    <span class="player-price">${p.price.toFixed(1)}m ${priceChangeIcon}</span>
                    <span style="color:var(--green)">${p.total_points || 0} pts</span>
                    ${p.form ? `<span>Form: ${p.form}</span>` : ''}
                    ${p.ict_index ? `<span>ICT: ${p.ict_index}</span>` : ''}
                    ${inSquad ? '<span style="color:var(--green)">✓ OWNED</span>' : ''}
                    ${p.is_injured ? '<span style="color:var(--red)">INJ</span>' : ''}
                </div>
            </div>
        `;
    }).join('');
}

// GAMEWEEKS
async function loadGameweeks() {
    try {
        const gameweeks = await api('/api/gameweeks/');
        const container = document.getElementById('gameweeks-container');
        if (!container) return;

        container.innerHTML = gameweeks.map(gw => `
            <div class="gameweek-card ${gw.closed ? 'closed' : ''} ${gw.scored ? 'scored' : ''}">
                <div class="gameweek-header">
                    <h4>Gameweek ${gw.number}</h4>
                    <span class="${gw.closed ? 'status-closed' : 'status-active'}">
                        ${gw.closed ? 'Closed' : 'Open'}
                    </span>
                </div>
                <div class="gameweek-details">
                    <p>Deadline: ${gw.deadline ? new Date(gw.deadline).toLocaleString() : 'N/A'}</p>
                    <p>${gw.scored ? '✓ Scored' : (gw.closed ? 'Pending score' : 'Open for transfers')}</p>
                </div>
            </div>
        `).join('');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// LEADERBOARD
async function loadLeaderboard() {
    try {
        const data = await api('/api/leaderboard/');
        state.leaderboard = data.entries || [];
        renderLeaderboard(state.leaderboard);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderLeaderboard(entries) {
    const container = document.getElementById('leaderboard-table');
    if (!container) return;

    if (!entries || entries.length === 0) {
        container.innerHTML = '<p>No entries yet.</p>';
        return;
    }

    container.innerHTML = `
        <table class="leaderboard-table">
            <thead>
                <tr>
                    <th>Rank</th>
                    <th>Manager</th>
                    <th>Team</th>
                    <th>GW Pts</th>
                    <th>Total</th>
                </tr>
            </thead>
            <tbody>
                ${entries.map(e => `
                    <tr class="${e.user_id === state.user?.id ? 'your-row' : ''}">
                        <td>${e.rank}</td>
                        <td>${e.username}</td>
                        <td>${e.team_name}</td>
                        <td>${e.gameweek_points ?? '-'}</td>
                        <td><strong>${e.total_points}</strong></td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

// LEAGUES
async function loadLeagues() {
    if (!state.user) {
        showPage('login');
        return;
    }

    try {
        const data = await api(`/api/leagues/my-leagues/${state.user.id}`);
        state.leagues = data.leagues || [];
        renderLeagues(state.leagues);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderLeagues(leagues) {
    const container = document.getElementById('leagues-container');
    if (!container) return;

    if (!leagues || leagues.length === 0) {
        container.innerHTML = '<p>You are not in any leagues yet. Create or join one!</p>';
        return;
    }

    container.innerHTML = leagues.map(l => `
        <div class="league-card">
            <h4>${l.name}</h4>
            <p>Members: ${l.member_count || 0} | Your Rank: ${l.your_rank || '-'}</p>
            <p>Code: <code>${l.code}</code></p>
            ${l.is_admin ? '<span style="color:var(--purple);font-size:0.75rem;">Admin</span>' : ''}
        </div>
    `).join('');
}

// HISTORY
async function loadHistory() {
    if (!state.user) {
        showPage('login');
        return;
    }

    try {
        const data = await api(`/api/users/${state.user.id}/team/history`);
        renderHistory(data);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderHistory(data) {
    const container = document.getElementById('history-container');
    if (!container) return;

    if (!data.history || data.history.length === 0) {
        container.innerHTML = '<p>No gameweek history yet.</p>';
        return;
    }

    container.innerHTML = `
        <h4>Team: ${data.team_name}</h4>
        <table class="leaderboard-table">
            <thead>
                <tr>
                    <th>GW</th>
                    <th>Points</th>
                    <th>Total</th>
                    <th>Rank</th>
                    <th>Chip</th>
                    <th>Transfers</th>
                </tr>
            </thead>
            <tbody>
                ${data.history.map(h => `
                    <tr>
                        <td>${h.gameweek}</td>
                        <td><strong>${h.points}</strong></td>
                        <td>${h.total_points}</td>
                        <td>${h.rank || '-'}</td>
                        <td>${h.chip_used || '-'}</td>
                        <td>${h.transfers_made}${h.transfers_cost ? ` (-${h.transfers_cost})` : ''}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

// Init
updateNav();
if (state.user) {
    showPage('my-team');
} else {
    showPage('home');
}
